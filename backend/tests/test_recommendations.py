"""Deterministic recommendation evidence and worker boundaries; no network/DB."""
import asyncio
from copy import deepcopy
from uuid import uuid4

import pytest

from backend.schemas.models import InterpretationOutput
from backend.services import recommendations
from backend.services.llm import LLMInvalidStructuredOutput


SESSION, SOURCE, CURRENT = map(str, (uuid4(), uuid4(), uuid4()))
JOB = dict(job_id=CURRENT, session_id=SESSION, request_text='2번으로 찾아줘', attempt=1, max_attempts=3)


def draft(name='앉기', term='sit', role='pose', unsupported=None):
    return dict(name=name, source_quote=name, terms=[dict(role=role, term_id=term,
        evidence=[name], confidence=1)], unsupported_constraints=unsupported or [])


def output(candidates=None, **kwargs):
    candidates = candidates or [draft('서기', 'stand'), draft()]
    return InterpretationOutput.model_validate(dict(interpretation_state='drawing_chat',
        answer_text='\n'.join(f'{index}. {candidate["source_quote"]}' for index, candidate in enumerate(candidates, 1)),
        recommendation_candidates=candidates, **kwargs))


def setup(snapshot_factory, card_factory, candidates=None):
    snapshot = snapshot_factory([card_factory('stand', label_ko='서기'), card_factory('sit', label_ko='앉기'),
        card_factory('low', role='composition', label_ko='로우앵글'), card_factory('high', role='composition', label_ko='하이앵글')])
    group = recommendations.create_group(dict(JOB, job_id=SOURCE), output(candidates), snapshot)
    context = dict(state={'recommendation_group': group.model_dump(mode='json')}, recent=[], sources=[])
    return snapshot, group, context


class Memory:
    def __init__(self, group, adoption=None, snapshot=None):
        self.group, self.queries = group, []
        self.adoption, self.snapshot = adoption, snapshot

    async def records(self, job, ids):
        self.queries.append(list(map(str, ids)))
        if self.adoption and list(map(str,ids)) == [self.adoption.get('adoption_job_id')]:
            return [dict(job_id=self.adoption['adoption_job_id'],request_text=self.adoption['request_text'],
                recommendation_adoption=self.adoption,terms=[{key:self.snapshot.get_active(term)[key]
                    for key in ('role','term_id','label_ko','label_en')} for term in self.adoption['search_term_ids']])]
        if str(self.group.session_id) != str(job['session_id']) or list(map(str, ids)) != [str(self.group.source_job_id)]:
            raise LLMInvalidStructuredOutput('foreign source')
        return [dict(job_id=str(self.group.source_job_id), request_text='포즈 추천해줘', terms=[],
            message='\n'.join(f'{c.ordinal}. {c.source_quote}' for c in self.group.candidates),
            question=None, recommendation_group=self.group.model_dump(mode='json'))]


def handle(snapshot, group, context, text='2번으로 찾아줘', interpreted=None):
    interpreted = interpreted or InterpretationOutput(interpretation_state='drawing_chat', answer_text='좋아요.')
    return asyncio.run(recommendations.handle(Memory(group,context['state'].get('recommendation_adoption'),snapshot),
        dict(JOB, request_text=text), interpreted, snapshot, context))


def test_optional_schema_and_numbered_server_bound_candidates(snapshot_factory, card_factory):
    snapshot, group, _ = setup(snapshot_factory, card_factory)
    assert [c.ordinal for c in group.candidates] == [1, 2]
    assert group.candidates[0].candidate_id != group.candidates[1].candidate_id
    assert group.source_job_id == SOURCE and group.session_id == SESSION
    assert recommendations.create_group(dict(JOB, job_id=SOURCE), output(), snapshot) == group
    assert InterpretationOutput(interpretation_state='drawing_chat', answer_text='연습해봐요.').recommendation_candidates == []


@pytest.mark.parametrize('text,term', [('2번으로 찾아줘','sit'), ('앉기로 찾아줘','sit'), ('1번으로 찾아줘','stand')])
def test_ordinal_and_name_adopt_only_selected_quote(snapshot_factory, card_factory, text, term):
    snapshot, group, context = setup(snapshot_factory, card_factory)
    decision = handle(snapshot, group, context, text)
    assert [t.selection.term_id for t in decision.resolution.terms] == [term]
    assert decision.adoption.candidate_id == next(c.candidate_id for c in group.candidates if c.terms[0].term_id == term)
    assert decision.adoption.request_text == text


def test_single_pointer_and_ambiguous_multi_are_distinct(snapshot_factory, card_factory):
    snapshot, group, context = setup(snapshot_factory, card_factory)
    decision = handle(snapshot, group, context, '방금 추천한 걸로 찾아줘')
    assert decision.result.agent_status == 'needs_clarification'
    assert decision.resolution is None and '번호' in decision.result.clarifying_question
    snapshot, group, context = setup(snapshot_factory, card_factory, [draft()])
    decision = handle(snapshot, group, context, '방금 추천한 걸로 찾아줘')
    assert [t.selection.term_id for t in decision.resolution.terms] == ['sit']


def test_one_shot_chooses_one_and_discloses_actual_conditions(snapshot_factory, card_factory):
    snapshot, _, _ = setup(snapshot_factory, card_factory)
    context = dict(state={}, recent=[], sources=[])
    decision = asyncio.run(recommendations.handle(None, dict(JOB, request_text='포즈 추천해서 바로 찾아줘'), output(), snapshot, context))
    assert [t.selection.term_id for t in decision.resolution.terms] == ['stand']
    assert '서기' in decision.interpretation.answer_text


def test_recommendation_only_has_no_search_even_if_model_selects(snapshot_factory, card_factory):
    snapshot, _, _ = setup(snapshot_factory, card_factory)
    interpreted = output().model_copy(update={'interpretation_state':'select_terms'})
    decision = asyncio.run(recommendations.handle(None, dict(JOB, request_text='포즈 추천해줘'), interpreted, snapshot,
        dict(state={},recent=[],sources=[])))
    assert decision.result.agent_status == 'drawing_chat'
    assert decision.resolution is None and decision.result.reference_plan is None
    assert decision.result.recommendation_group is not None


def test_current_override_preserves_other_candidate_conditions(snapshot_factory, card_factory):
    snapshot, group, context = setup(snapshot_factory, card_factory,
        [draft('서기','stand'), dict(name='앉기',source_quote='앉기',terms=draft()['terms'],unsupported_constraints=[])])
    interpreted = InterpretationOutput(interpretation_state='select_terms', answer_text='로우앵글로 찾아요.',
        selections=[dict(role='composition',term_id='low',evidence=['로우앵글'],confidence=1)])
    decision = handle(snapshot, group, context, '2번인데 로우앵글', interpreted)
    assert [t.selection.term_id for t in decision.resolution.terms] == ['sit','low']


@pytest.mark.parametrize('change', ['foreign_session', 'tampered_quote', 'fabricated_source', 'foreign_model_source'])
def test_unowned_or_fabricated_recommendations_are_rejected(snapshot_factory, card_factory, change):
    snapshot, group, context = setup(snapshot_factory, card_factory)
    interpreted = None
    if change == 'foreign_session':
        context['state']['recommendation_group']['session_id'] = str(uuid4())
    elif change == 'tampered_quote':
        context['state']['recommendation_group']['candidates'][1]['source_quote'] = '가짜'
    elif change == 'fabricated_source':
        context['state']['recommendation_group']['source_job_id'] = str(uuid4())
    else:
        interpreted = InterpretationOutput(interpretation_state='select_terms',answer_text='찾아요.',selections=[
            dict(role='pose',term_id='stand',evidence=['서기'],confidence=1,source_job_id=str(uuid4()))])
    with pytest.raises(LLMInvalidStructuredOutput):
        handle(snapshot, group, context, interpreted=interpreted)


@pytest.mark.parametrize('bad', ['quote', 'evidence', 'inactive', 'source_job'])
def test_creation_validates_original_answer_and_terms(snapshot_factory, card_factory, bad):
    snapshot, _, _ = setup(snapshot_factory, card_factory)
    interpreted = output()
    if bad == 'quote': interpreted.recommendation_candidates[1].source_quote = '없는 문장'
    if bad == 'evidence': interpreted.recommendation_candidates[1].terms[0].evidence = ['없는 근거']
    if bad == 'inactive': interpreted.recommendation_candidates[1].terms[0].term_id = 'absent'
    if bad == 'source_job': interpreted.recommendation_candidates[1].terms[0].source_job_id = uuid4()
    with pytest.raises(LLMInvalidStructuredOutput):
        recommendations.create_group(dict(JOB, job_id=SOURCE), interpreted, snapshot)


@pytest.mark.parametrize('disabled', [False, True])
def test_adoption_revalidates_catalog_and_blocks_without_search(snapshot_factory, card_factory, disabled):
    snapshot, group, context = setup(snapshot_factory, card_factory)
    if disabled:
        snapshot = snapshot_factory(list(snapshot.active_cards.values()), dsd=('sit',))
    else:
        snapshot.active_cards.pop('sit')
    decision = handle(snapshot, group, context)
    assert decision.result.agent_status == 'reference_guidance'
    assert decision.adoption.status == 'blocked' and decision.resolution is None


def test_unsupported_core_is_explained_and_not_silently_dropped(snapshot_factory, card_factory):
    unsupported = dict(draft(unsupported=['네 팔']), source_quote='네 팔 앉기')
    snapshot, group, context = setup(snapshot_factory, card_factory, [draft('서기','stand'),unsupported])
    decision = handle(snapshot, group, context)
    assert decision.resolution is None and decision.result.agent_status == 'reference_guidance'
    assert '네 팔' in decision.result.user_message
    assert decision.adoption.status == 'blocked'


def test_explicit_topic_reset_clears_recommendations_and_old_constraints():
    context = dict(state={'recommendation_group':{'old':True},'recommendation_adoption':{'old':True},
        'constraints':{'old':{}},'pending_question':'old'},previous_result={'old':True},recent=[],sources=[])
    recommendations.reset_context(dict(JOB,request_text='새 주제로 바꿀게. 인체 연습 방법 알려줘'),context)
    assert context['state']['recommendation_group'] is None
    assert context['state']['constraints'] == {} and not context['previous_result']


def test_unrelated_search_does_not_adopt_previous_suggestion(snapshot_factory, card_factory):
    snapshot, group, context = setup(snapshot_factory, card_factory)
    assert handle(snapshot, group, context, '원근법 레퍼런스 찾아줘') is None


@pytest.mark.parametrize('text', ['레퍼런스는 찾지 말고 아이디어만 추천해줘', '추천한 이미지가 왜 좋아?'])
def test_search_nouns_and_negated_verbs_do_not_authorize_search(snapshot_factory, card_factory, text):
    snapshot, group, context = setup(snapshot_factory, card_factory)
    interpreted = output() if recommendations.generates_recommendations(text) else None
    decision = handle(snapshot, group, context, text, interpreted)
    assert decision is None or decision.resolution is None


def test_multi_candidate_retry_pointer_uses_last_adoption(snapshot_factory, card_factory):
    snapshot, group, context = setup(snapshot_factory, card_factory)
    chosen = handle(snapshot, group, context)
    chosen.adoption.status = 'search_failed'
    state = recommendations.next_state(context['state'], JOB, chosen)
    decision = handle(snapshot, group, dict(context, state=state), '그걸로 다시 찾아줘')
    assert decision.adoption.candidate_id == group.candidates[1].candidate_id
    assert [term.selection.term_id for term in decision.resolution.terms] == ['sit']


def test_unrelated_new_search_clears_stale_suggestion_state(snapshot_factory, card_factory):
    _, _, context = setup(snapshot_factory, card_factory)
    state = recommendations.next_state(context['state'],dict(JOB, request_text='원근법 레퍼런스 찾아줘'),None)
    assert state['recommendation_group'] is None


def test_confirmed_user_condition_overrides_candidate_supplement(snapshot_factory, card_factory):
    snapshot, group, context = setup(snapshot_factory, card_factory)
    old = str(uuid4())
    context['state']['constraints'] = {'stand':dict(role='pose',term_id='stand',evidence='서기',source_job_id=old)}
    memory = Memory(group)
    original_records = memory.records
    async def records(job, ids):
        if list(map(str,ids)) == [old]:
            return [dict(job_id=old,request_text='서기로 할게',terms=[],question=None,message='')]
        return await original_records(job,ids)
    memory.records = records
    decision = asyncio.run(recommendations.handle(memory,JOB,
        InterpretationOutput(interpretation_state='drawing_chat',answer_text='좋아요.'),snapshot,context))
    assert [t.selection.term_id for t in decision.resolution.terms] == ['stand']
    explicit = InterpretationOutput(interpretation_state='select_terms',answer_text='앉기로 바꿔요.',selections=[
        dict(role='pose',term_id='sit',evidence=['앉기'],confidence=1)])
    decision = asyncio.run(recommendations.handle(memory,dict(JOB,request_text='2번인데 앉기로 바꿔줘'),explicit,snapshot,context))
    assert [t.selection.term_id for t in decision.resolution.terms] == ['sit']


def test_worker_recommendation_then_adoption_failure_reload_retry(monkeypatch, snapshot_factory, card_factory):
    from backend.services.agent_worker import AgentJobWorker
    from backend.schemas.enums import Role, JobStatus, ReasonCode
    from backend.services.response_assembler import RoleSearchOutcome
    from backend.tests.test_agent_worker import FakeJobs, FakeRecovery, FakeAdapter
    from backend.services import agent_worker
    snapshot, _, _ = setup(snapshot_factory,card_factory)
    jobs, recovery = FakeJobs(dict(JOB,job_id=SOURCE,request_text='포즈 추천해줘')), FakeRecovery()
    adapter = FakeAdapter(output())
    context = dict(state={},recent=[],sources=[])
    completed = []
    saved = []
    class WorkerMemory:
        async def load(self, job): return deepcopy(context)
        async def records(self, job, ids):
            from backend.services.conversation_memory import record
            matches=[record(dict(status='completed',job_id=source['job_id'],request_text=source['request_text'],
                final_payload_json=result.model_dump(mode='json')),include_recommendations=True)
                for source,result in saved if source['job_id'] in list(map(str,ids))]
            if matches:return matches
            return await Memory(completed[0].recommendation_group).records(job,ids)
        async def complete(self, job, result, state):
            completed.append(result)
            saved.append((dict(job),result))
            context['state'] = deepcopy(state)
            await jobs.update_status(job_id=job['job_id'],attempt=job['attempt'],status=JobStatus.COMPLETED,result=result)
    monkeypatch.setattr(agent_worker,'JobRepository',lambda pool:jobs)
    monkeypatch.setattr(agent_worker,'JobRetryRecovery',lambda pool:recovery)
    monkeypatch.setattr(agent_worker,'ConversationMemory',lambda pool:WorkerMemory())
    worker = AgentJobWorker(None,snapshot,adapter=adapter)
    searches = []
    async def search(resolution, **kwargs):
        searches.append([term.selection.term_id for term in resolution.terms])
        return {'sit':RoleSearchOutcome(role=Role.POSE,code=ReasonCode.PIN_RESULTS_EMPTY)}
    worker._search_outcomes = search
    asyncio.run(worker.run_once())
    assert completed[-1].agent_status == 'drawing_chat' and searches == []
    adapter.output = InterpretationOutput(interpretation_state='drawing_chat',answer_text='좋아요.')
    jobs.job = dict(JOB,job_id=str(uuid4()),request_text='방금 추천한 걸로 찾아줘')
    asyncio.run(worker.run_once())
    assert completed[-1].agent_status == 'needs_clarification' and searches == []
    from backend.services.resolver import resolve
    from backend.services.response_assembler import assemble
    old = InterpretationOutput(interpretation_state='select_terms', answer_text='서기',selections=[
        dict(role='pose',term_id='stand',evidence=['서기'],confidence=1)])
    context['previous_result'] = assemble(resolve(old,snapshot,request_text='서기'),snapshot).model_dump(mode='json')
    adapter.output = InterpretationOutput(interpretation_state='drawing_chat',answer_text='좋아요.')
    jobs.job = dict(JOB,request_text='2번')
    asyncio.run(worker.run_once())
    assert not recovery.failures
    assert [term.term_id for term in completed[-1].reference_plan.terms] == ['sit']
    assert completed[-1].recommendation_adoption.status == 'search_failed'
    # New worker + JSON serialization simulate process/session restoration.
    import json
    context['state'] = json.loads(json.dumps(context['state']))
    retry = AgentJobWorker(None,snapshot,adapter=adapter)
    retry._search_outcomes = search
    jobs.job = dict(JOB,job_id=str(uuid4()),request_text='그걸로 다시 찾아줘')
    asyncio.run(retry.run_once())
    assert searches == [['sit'],['sit']]
    assert not recovery.failures


def test_strict_catalog_schema_resolves_every_ref_including_recommendation_terms():
    from backend.services.structured_output import response_format, routed_response_format
    import json
    for build in (response_format,routed_response_format):
        schema = build(json.dumps({'active_cards':[{'role':'pose','term_id':'sit'}]}))['json_schema']['schema']
        def visit(value):
            if isinstance(value,dict):
                if '$ref' in value:
                    current = schema
                    for key in value['$ref'][2:].split('/'): current = current[key]
                for item in value.values(): visit(item)
            if isinstance(value,list):
                for item in value: visit(item)
        visit(schema)
        assert schema['$defs']['RecommendationDraft']['properties']['terms']['items']['anyOf'] == [
            {'$ref':'#/$defs/InterpretationSelection_pose'}]


def test_one_shot_with_existing_group_creates_new_owned_group(snapshot_factory,card_factory):
    snapshot, group, context = setup(snapshot_factory,card_factory)
    decision = handle(snapshot,group,context,'추천해서 바로 찾아줘',output())
    assert decision.resolution is not None
    assert decision.group.source_job_id == CURRENT
    assert decision.group.group_id != group.group_id


def test_new_subject_evidence_clears_old_user_constraints(snapshot_factory,card_factory):
    snapshot,group,context = setup(snapshot_factory,card_factory)
    context['state']['constraints'] = {'stand':dict(role='pose',term_id='stand',evidence='서기',source_job_id=SOURCE)}
    interpreted = output().model_copy(update={'topic_reset_evidence':'동물 캐릭터'})
    decision = handle(snapshot,group,context,'이번엔 동물 캐릭터 아이디어 추천해줘',interpreted)
    assert decision.result.agent_status == 'drawing_chat'
    assert context['state']['constraints'] == {}


def test_fake_topic_reset_evidence_is_rejected(snapshot_factory,card_factory):
    snapshot,group,context = setup(snapshot_factory,card_factory)
    interpreted = output().model_copy(update={'topic_reset_evidence':'없는 주제'})
    with pytest.raises(LLMInvalidStructuredOutput):
        handle(snapshot,group,context,'포즈 추천해줘',interpreted)


def test_legacy_recommendation_pointer_asks_selection_without_search(snapshot_factory):
    context = dict(state={},recent=[dict(job_id=SOURCE,message='앉은 포즈를 추천해요.',terms=[],request_text='포즈 추천',question=None)],sources=[])
    interpreted = InterpretationOutput(interpretation_state='drawing_chat',answer_text='좋아요.')
    decision = asyncio.run(recommendations.handle(None,dict(JOB,request_text='방금 추천한 걸로 찾아줘'),interpreted,snapshot_factory([]),context))
    assert decision.resolution is None and decision.result.agent_status == 'needs_clarification'
    assert '번호' in decision.result.clarifying_question


def test_full_original_quote_survives_verification_without_prompt_duplication(snapshot_factory,card_factory):
    from backend.services.conversation_memory import record
    from backend.services.conversation_context import prompt_context
    long = dict(draft(), source_quote='긴 설명 ' * 220 + ' 앉기')
    snapshot,group,context = setup(snapshot_factory,card_factory,[draft('서기','stand'),long])
    answer = output([draft('서기','stand'),long]).answer_text
    payload = dict(agent_status='drawing_chat',answer_text=answer,recommendation_group=group.model_dump(mode='json'))
    row = dict(status='completed',job_id=SOURCE,request_text='포즈 추천해줘',final_payload_json=payload)
    recent = record(row)
    original = record(row,include_recommendations=True)
    assert len(recent['message']) == 1000 and 'recommendation_group' not in recent
    assert original['recommendation_answer'] == answer
    context.update(recent=[recent]*6,sources=[original])
    prompt = prompt_context(context)
    assert all('recommendation_group' not in item and 'recommendation_answer' not in item for item in prompt['recent']+prompt['sources'])
    class OriginalMemory:
        async def records(self,job,ids): return [original]
    decision = asyncio.run(recommendations.handle(OriginalMemory(),JOB,
        InterpretationOutput(interpretation_state='drawing_chat',answer_text='좋아요.'),snapshot,context))
    assert [term.selection.term_id for term in decision.resolution.terms] == ['sit']


def test_memory_json_load_and_atomic_complete_preserve_bounded_recommendation_fields(monkeypatch,snapshot_factory,card_factory):
    import json
    from backend.services import conversation_memory
    from backend.services.conversation_memory import ConversationMemory
    from backend.schemas.models import AgentResult
    _,group,_ = setup(snapshot_factory,card_factory)
    class Scope:
        def __init__(self,value): self.value=value
        async def __aenter__(self): return self.value
        async def __aexit__(self,*args): pass
    class Pool:
        stored = {}
        def acquire(self): return Scope(self)
        def transaction(self): return Scope(self)
        async def fetchval(self,query,*args):
            if 'FOR UPDATE' in query: return SESSION
            if 'SELECT memory_json' in query: return json.dumps(self.stored)
            if 'SELECT final_payload_json' in query:
                assert "recommendation_adoption'->>'status'" in query
                return None
            raise AssertionError(query)
        async def fetch(self,query,*args): return []
        async def execute(self,query,*args): self.stored.update(json.loads(args[1]))
    writes=[]
    class Jobs:
        def __init__(self,pool): pass
        async def update_status(self,**kwargs): writes.append(kwargs)
    monkeypatch.setattr(conversation_memory,'JobRepository',Jobs)
    pool=Pool()
    memory=ConversationMemory(pool)
    result=AgentResult(agent_status='drawing_chat',answer_text='추천해요.',recommendation_group=group)
    job=dict(JOB,created_at='now')
    asyncio.run(memory.complete(job,result,dict(constraints={},recommendation_group=group.model_dump(mode='json'),recommendation_adoption=None,untrusted='discard')))
    restored=asyncio.run(memory.load(job))
    assert restored['state']['recommendation_group'] == group.model_dump(mode='json')
    assert restored['state']['recommendation_adoption'] is None and 'untrusted' not in pool.stored
    assert writes[0]['result'] is result


def test_new_generative_request_rejects_model_single_candidate_but_stored_single_can_adopt(snapshot_factory,card_factory):
    snapshot,group,context = setup(snapshot_factory,card_factory,[draft()])
    with pytest.raises(LLMInvalidStructuredOutput):
        handle(snapshot,group,context,'포즈 추천해줘',output([draft()]))
    assert handle(snapshot,group,context,'방금 추천한 걸로 찾아줘').resolution is not None


def test_real_adapter_parses_recommendations_using_fake_transport(snapshot_factory,card_factory):
    import json
    from backend.tests.test_llm_adapter import _adapter,_FakeCompletions,_FakeResponse
    from backend.services.llm import format_active_cards_json
    snapshot,_,_=setup(snapshot_factory,card_factory)
    completions=_FakeCompletions([_FakeResponse(output().model_dump_json())])
    from backend.shared.config import Settings
    adapter=_adapter(completions,settings=Settings(_env_file=None,database_url='sqlite:///./t17-test.db',
        interpreter_prompt_version='uhkegryo-interpreter-v4'))
    interpreted=asyncio.run(adapter.interpret('포즈 추천해줘',active_cards_json=format_active_cards_json(snapshot),
        job_id=CURRENT,session_id=SESSION,attempt=1,max_attempts=3))
    assert len(interpreted.recommendation_candidates)==2
    schema=completions.calls[0]['response_format']['json_schema']['schema']
    assert 'recommendation_candidates' in schema['properties']
    assert 'RecommendationDraft' in schema['$defs']


def test_current_override_of_inactive_candidate_condition_is_explicit(snapshot_factory,card_factory):
    snapshot,group,context=setup(snapshot_factory,card_factory)
    snapshot.active_cards.pop('sit')
    interpreted=InterpretationOutput(interpretation_state='select_terms',answer_text='서기로 바꿔요.',selections=[
        dict(role='pose',term_id='stand',evidence=['서기'],confidence=1)])
    decision=handle(snapshot,group,context,'2번인데 서기로 바꿔줘',interpreted)
    assert decision.resolution is not None
    assert [term.selection.term_id for term in decision.resolution.terms]==['stand']


@pytest.mark.parametrize('answer',['2','2번','앉기'])
def test_pending_selection_authorizes_bare_answer_after_json_reload(snapshot_factory,card_factory,answer):
    import json
    snapshot,group,context=setup(snapshot_factory,card_factory)
    question=handle(snapshot,group,context,'방금 추천한 걸로 찾아줘')
    state=recommendations.next_state(context['state'],JOB,question)
    restored=dict(context,state=json.loads(json.dumps(state)))
    chat=handle(snapshot,group,restored,'2번은 왜 좋아?')
    assert chat is None or chat.resolution is None
    selected=handle(snapshot,group,restored,answer)
    assert [term.selection.term_id for term in selected.resolution.terms]==['sit']


def test_reversed_model_numbering_cannot_change_displayed_selection_identity(snapshot_factory,card_factory):
    snapshot,_,_=setup(snapshot_factory,card_factory)
    interpreted=output()
    interpreted.recommendation_candidates.reverse()
    with pytest.raises(LLMInvalidStructuredOutput):
        recommendations.create_group(dict(JOB,job_id=SOURCE),interpreted,snapshot)


def test_failed_retry_retains_effective_current_override(snapshot_factory,card_factory):
    snapshot,group,context=setup(snapshot_factory,card_factory)
    interpreted=InterpretationOutput(interpretation_state='select_terms',answer_text='로우앵글',selections=[
        dict(role='composition',term_id='low',evidence=['로우앵글'],confidence=1)])
    first=handle(snapshot,group,context,'2번인데 로우앵글',interpreted)
    first.adoption.status='search_failed'
    state=recommendations.next_state(context['state'],JOB,first)
    retry=handle(snapshot,group,dict(context,state=state),'그걸로 다시 찾아줘')
    assert [term.selection.term_id for term in retry.resolution.terms]==['sit','low']


def test_real_catalog_view_override_preserves_independent_layout():
    from pathlib import Path
    from backend.services.catalog_repository import load_catalog
    snapshot=load_catalog(Path(__file__).parents[2]/'docs/domains/illustration-reference/term-cards')
    def selection(term):
        card=snapshot.get_active(term)
        return dict(role=card['role'],term_id=term,evidence=[card['label_ko']],confidence=1)
    terms=[selection(term) for term in ('view_profile','view_high_angle','composition_rule_of_thirds')]
    quote='구도 '+', '.join(snapshot.get_active(term)['label_ko'] for term in ('view_profile','view_high_angle','composition_rule_of_thirds'))
    proposed=output([dict(name='구도',source_quote=quote,terms=terms,unsupported_constraints=[])])
    group=recommendations.create_group(dict(JOB,job_id=SOURCE),proposed,snapshot)
    context=dict(state={'recommendation_group':group.model_dump(mode='json')},recent=[],sources=[])
    front=snapshot.get_active('view_front')['label_ko']
    interpreted=InterpretationOutput(interpretation_state='select_terms',answer_text='정면으로 바꿔요.',selections=[selection('view_front')])
    decision=handle(snapshot,group,context,f'1번인데 {front}으로 바꿔줘',interpreted)
    assert {term.selection.term_id for term in decision.resolution.terms}=={'view_front','view_high_angle','composition_rule_of_thirds'}


def test_ordinary_history_recall_is_not_recommendation_generation(snapshot_factory,card_factory):
    _,_,context=setup(snapshot_factory,card_factory)
    assert not recommendations.has_intent(dict(JOB,request_text='지난주에 뭘 추천했지?'),context)
    assert not recommendations.has_intent(dict(JOB,request_text='추천한 이미지가 왜 좋아?'),context)


def test_missing_structured_candidates_on_new_recommendation_requires_repair(snapshot_factory):
    with pytest.raises(LLMInvalidStructuredOutput):
        asyncio.run(recommendations.handle(None,dict(JOB,request_text='아이디어 추천해줘'),
            InterpretationOutput(interpretation_state='drawing_chat',answer_text='1. 첫째\n2. 둘째'),snapshot_factory([]),
            dict(state={},recent=[],sources=[])))


def test_explicit_negative_selection_does_not_adopt(snapshot_factory,card_factory):
    snapshot,group,context=setup(snapshot_factory,card_factory)
    decision=handle(snapshot,group,context,'2번으로 찾지 말고 설명만 해줘')
    assert decision.adoption is None and decision.resolution is None


def test_one_shot_original_answer_survives_actual_condition_message(snapshot_factory,card_factory):
    from backend.services.conversation_memory import record
    from backend.services.response_assembler import assemble
    snapshot,_,_=setup(snapshot_factory,card_factory)
    context=dict(state={},recent=[],sources=[])
    first=asyncio.run(recommendations.handle(None,dict(JOB,request_text='포즈 추천해서 바로 찾아줘'),output(),snapshot,context))
    result=recommendations.finish(assemble(first.resolution,snapshot,answer_text=first.interpretation.answer_text),first)
    original=record(dict(job_id=CURRENT,status='completed',request_text='포즈 추천해서 바로 찾아줘',
        final_payload_json=result.model_dump(mode='json')),include_recommendations=True)
    context['state']=recommendations.next_state({},JOB,first)
    class OriginalMemory:
        async def records(self,job,ids):return [original]
    adopted=asyncio.run(recommendations.handle(OriginalMemory(),dict(JOB,job_id=str(uuid4()),request_text='2번으로 찾아줘'),
        InterpretationOutput(interpretation_state='drawing_chat',answer_text='좋아요.'),snapshot,context))
    assert [term.selection.term_id for term in adopted.resolution.terms]==['sit']


@pytest.mark.parametrize('recall_text',[None,'지난주에 뭘 추천했지?','지난주에 2번으로 찾아달라고 했던 거 기억나?'])
def test_worker_topic_change_and_normal_recall_keep_existing_boundaries(monkeypatch,snapshot_factory,card_factory,recall_text):
    from backend.tests.test_agent_worker import FakeAdapter,FakeJobs,FakeRecovery,_worker
    from backend.schemas.memory import RecallQuery
    from backend.services.resolver import resolve
    from backend.services.response_assembler import assemble
    snapshot,group,context=setup(snapshot_factory,card_factory)
    old=InterpretationOutput(interpretation_state='select_terms',answer_text='앉기',selections=[
        dict(role='pose',term_id='sit',evidence=['앉기'],confidence=1)])
    context['previous_result']=assemble(resolve(old,snapshot,request_text='앉기'),snapshot).model_dump(mode='json')
    interpreted=InterpretationOutput(interpretation_state='select_terms',answer_text='서기',topic_reset_evidence='동물 캐릭터',selections=[
        dict(role='pose',term_id='stand',evidence=['서기'],confidence=1)])
    jobs=FakeJobs(dict(JOB,request_text=recall_text or '동물 캐릭터 서기로 찾아줘'))
    recovery=FakeRecovery()
    adapter=FakeAdapter(interpreted)
    memory_calls=[]
    async def classify(*args,**kwargs):
        memory_calls.append('classify')
        return RecallQuery(mode='recall' if recall_text else 'none')
    adapter.memory=classify
    worker=_worker(monkeypatch,jobs,recovery,snapshot,adapter)
    completed=[]
    class ScopedMemory:
        async def load(self,job):return deepcopy(context)
        async def search(self,job,query):return []
        async def complete(self,job,result,state):completed.append((result,state))
    worker._memory=ScopedMemory()
    asyncio.run(worker.run_once(search_outcomes={}))
    assert not recovery.failures
    result,state=completed[0]
    if recall_text:
        assert memory_calls==['classify'] and result.agent_status=='memory_answer'
        assert not adapter.calls
    else:
        assert [term.term_id for term in result.reference_plan.terms]==['stand']
        assert state['recommendation_group'] is None and state['constraints']=={}


def test_historical_quoted_search_keeps_recall_routing_and_current_mixed_selection(snapshot_factory,card_factory):
    snapshot,group,context=setup(snapshot_factory,card_factory)
    historical='지난주에 2번으로 찾아달라고 했던 거 기억나?'
    assert not recommendations.has_intent(dict(JOB,request_text=historical),context)
    assert handle(snapshot,group,context,historical) is None
    mixed=historical+' 이번엔 1번으로 찾아줘'
    assert not recommendations.has_intent(dict(JOB,request_text=mixed),context)
    chosen=handle(snapshot,group,context,mixed)
    assert [term.selection.term_id for term in chosen.resolution.terms]==['stand']


def test_bare_digit_without_pending_search_and_conversational_digit_question_do_not_adopt(snapshot_factory,card_factory):
    snapshot,group,context=setup(snapshot_factory,card_factory)
    assert handle(snapshot,group,context,'2') is None
    question=handle(snapshot,group,context,'방금 추천한 걸로 찾아줘')
    state=recommendations.next_state(context['state'],JOB,question)
    assert handle(snapshot,group,dict(context,state=state),'2는 왜 좋아?') is None


def real_group(term_ids):
    from pathlib import Path
    from backend.services.catalog_repository import load_catalog
    snapshot=load_catalog(Path(__file__).parents[2]/'docs/domains/illustration-reference/term-cards')
    terms=[dict(role=snapshot.get_active(term)['role'],term_id=term,
        evidence=[snapshot.get_active(term)['label_ko']],confidence=1) for term in term_ids]
    quote='선택 후보 '+', '.join(snapshot.get_active(term)['label_ko'] for term in term_ids)
    group=recommendations.create_group(dict(JOB,job_id=SOURCE),output([
        dict(name='선택 후보',source_quote=quote,terms=terms,unsupported_constraints=[])]),snapshot)
    return snapshot,group,dict(state={'recommendation_group':group.model_dump(mode='json')},recent=[],sources=[])


def test_additive_real_catalog_modifiers_do_not_erase_each_other():
    snapshot,group,context=real_group(['pose_standing','pose_twisting'])
    card=snapshot.get_active('pose_reaching')
    text='1번인데 '+card['label_ko']+'를 추가해서 찾아줘'
    interpreted=InterpretationOutput(interpretation_state='select_terms',answer_text='동작을 추가해요.',selections=[
        dict(role='pose',term_id='pose_reaching',evidence=[card['label_ko']],confidence=1)])
    decision=handle(snapshot,group,context,text,interpreted)
    assert {term.selection.term_id for term in decision.resolution.terms}=={'pose_standing','pose_twisting','pose_reaching'}


def test_removal_only_adoption_is_valid_schema_and_fake_transport_output():
    import json
    from backend.shared.config import Settings
    from backend.tests.test_llm_adapter import _adapter,_FakeCompletions,_FakeResponse
    from backend.services.llm import format_active_cards_json
    snapshot,group,context=real_group(['pose_standing','view_high_angle'])
    text='1번인데 하이 앵글만 빼고 찾아줘'
    payload=dict(interpretation_state='select_terms',answer_text='하이 앵글만 제외해요.',selections=[],context_updates=[
        dict(role='composition',term_id=None,evidence='하이 앵글만 빼고',remove_term_ids=['view_high_angle'])])
    payload=InterpretationOutput.model_validate(payload).model_dump(mode='json')
    completions=_FakeCompletions([_FakeResponse(json.dumps(payload,ensure_ascii=False))])
    adapter=_adapter(completions,settings=Settings(_env_file=None,database_url='sqlite:///./t17-test.db',
        interpreter_prompt_version='uhkegryo-interpreter-v4'))
    interpreted=asyncio.run(adapter.interpret(text,active_cards_json=format_active_cards_json(snapshot),
        job_id=CURRENT,session_id=SESSION,attempt=1,max_attempts=3))
    assert interpreted.selections==[]
    decision=handle(snapshot,group,context,text,interpreted)
    assert [term.selection.term_id for term in decision.resolution.terms]==['pose_standing']
    with pytest.raises(ValueError):
        InterpretationOutput(interpretation_state='select_terms',answer_text='조건이 없어요.',selections=[])
    with pytest.raises(ValueError):
        InterpretationOutput(interpretation_state='drawing_chat',answer_text='대화',context_updates=payload['context_updates'])
    invalid=interpreted.model_copy(deep=True)
    invalid.context_updates[0].evidence='없는 근거'
    with pytest.raises(LLMInvalidStructuredOutput):
        handle(snapshot,group,context,text,invalid)

