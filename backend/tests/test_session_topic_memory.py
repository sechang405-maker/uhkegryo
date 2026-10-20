"""Source-backed topic memory remains separate from confirmed search conditions."""
import asyncio
from copy import deepcopy
from uuid import UUID

import pytest

from backend.schemas.models import AgentResult, InterpretationOutput
from backend.services import conversation_context as cc, recommendations
from backend.tests.test_contextual_reference import Memory, context, row, chat, OLD

NEW = '00000000-0000-4000-8000-000000000020'


@pytest.fixture
def catalog(card_factory, snapshot_factory):
    return snapshot_factory([
        card_factory('composition_rule_of_thirds', role='composition', label_ko='삼분할 구도', label_en='rule of thirds'),
        card_factory('layout_composition', role='composition', label_ko='구도', label_en='composition'),
        card_factory('pose_sitting', label_ko='앉은 자세', label_en='sitting'),
    ])


def explained(catalog):
    original = row(request='삼분할 구도가 뭐야?', message='삼분할 구도와 앉은 자세를 설명해요.')
    state = cc.next_state(context(), {'job_id': OLD, 'request_text': original['request_text']},
        chat(), AgentResult(agent_status='drawing_chat', answer_text=original['message']), snapshot=catalog)
    return original, state


def test_explanation_records_only_literal_user_topic_without_confirming_it(catalog):
    original, state = explained(catalog)
    assert state['constraints'] == {}
    assert state['current_topic']['request_text'] == original['request_text']
    assert [t['term_id'] for t in state['current_topic']['terms']] == ['composition_rule_of_thirds']
    assert state['current_topic']['terms'][0]['source_job_id'] == OLD


@pytest.mark.parametrize('text', ['그리고 싶어', '그런 구도로 그리고 싶어', '찾아줘'])
@pytest.mark.parametrize('selected', [False, True])
def test_topic_adoption_searches_only_specific_composition_and_rereads_source(catalog, text, selected):
    original, state = explained(catalog)
    ctx = context(); ctx['state'] = state
    memory = Memory([original])
    interpretation = (InterpretationOutput(interpretation_state='select_terms', answer_text='찾아요.', selections=[
        dict(role='composition',term_id='layout_composition', evidence=['구도'],confidence=1,source_job_id=OLD)
    ]) if selected else chat())
    out = asyncio.run(cc.reference_fallback(memory, {'job_id': NEW, 'request_text': text}, interpretation, catalog, ctx))
    assert [t.term_id for t in out.selections] == ['composition_rule_of_thirds']
    assert out.selections[0].source_job_id == UUID(OLD)
    assert memory.reads and all(ids == (OLD,) for ids in memory.reads)


def test_twenty_turn_topic_survives_without_scanning_arbitrary_assistant_text(catalog):
    original, state = explained(catalog)
    for index in range(20):
        state = cc.next_state({'state':state}, {'job_id': NEW,'request_text':'고마워'}, chat(),
            AgentResult(agent_status='drawing_chat',answer_text='앉은 자세도 있어요.'), snapshot=catalog)
    ctx = context(); ctx['state'] = state
    out = asyncio.run(cc.reference_fallback(Memory([original]),{'job_id':NEW,'request_text':'그리고 싶어'},chat(),catalog,ctx))
    assert [t.term_id for t in out.selections] == ['composition_rule_of_thirds']


@pytest.mark.parametrize('text', ['새로 시작하자', '새 캐릭터를 그리고 싶어', '다른 주제로 이야기하자'])
def test_explicit_reset_clears_all_topic_owned_state_and_board(catalog, text):
    original, state = explained(catalog)
    state.update(constraints={'x':{}},excluded_conditions={'x':{}}, recommendation_group={'old':True})
    ctx = dict(state=state, recent=[original], sources=[original], previous_result={'old':True})
    recommendations.reset_context({'job_id':NEW,'request_text':text},ctx)
    assert ctx['state']['current_topic'] is None
    assert ctx['state']['constraints'] == ctx['state']['excluded_conditions'] == {}
    assert ctx['state']['recommendation_group'] is None
    assert ctx['previous_result'] == {} and ctx['recent'] == []


@pytest.mark.parametrize('text', ['새 캐릭터 말고 그대로', '새로 시작하지 마', '다른 주제로 바꾸지 말고',
    '"새 캐릭터"라는 말이야', '"새로 시작하자"라는 표현이야'])
def test_negated_or_quoted_reset_keeps_topic(catalog, text):
    original, state = explained(catalog)
    expected = deepcopy(state)
    ctx = context(original); ctx['state'] = state
    recommendations.reset_context({'job_id':NEW,'request_text':text},ctx)
    assert ctx['state'] == expected


def test_new_character_variant_resets_topic(catalog):
    original, state = explained(catalog)
    ctx = context(original); ctx['state'] = state
    recommendations.reset_context({'job_id':NEW,'request_text':'새로운 캐릭터를 그리고 싶어'},ctx)
    assert ctx['state']['current_topic'] is None


@pytest.mark.parametrize('text', ['"그리고 싶어"라는 말이야', '검색하지 마', '어떻게 그려?'])
def test_topic_does_not_override_quote_negative_or_howto(catalog, text):
    original, state = explained(catalog)
    ctx = context(original); ctx['state'] = state
    memory = Memory([original])
    out = asyncio.run(cc.reference_fallback(memory, {'job_id':NEW,'request_text':text},chat(),catalog,ctx))
    assert out.interpretation_state == 'drawing_chat' and out.selections == []
    assert memory.reads == []


def test_add_pose_then_remove_topic_and_never_restore_twenty_turns_later(catalog):
    from backend.services.response_assembler import assemble
    from backend.services.llm import LLMInvalidStructuredOutput
    original, state = explained(catalog)
    ctx = context(original); ctx['state'] = state
    memory = Memory([original])
    first = asyncio.run(cc.reference_fallback(memory, {'job_id':NEW,'request_text':'그리고 싶어'},chat(),catalog,ctx))
    result = assemble(asyncio.run(cc.validate(memory,{'request_text':'그리고 싶어'},first,catalog,context=ctx)),catalog)
    state = cc.next_state(ctx, {'job_id':NEW,'request_text':'그리고 싶어'},first,result,snapshot=catalog)
    ctx['state'] = state
    edit_job = {'job_id': '00000000-0000-4000-8000-000000000021', 'request_text':'앉은 자세로'}
    edit = InterpretationOutput(interpretation_state='select_terms',answer_text='앉은 자세로 찾아요.',selections=[
        dict(role='pose',term_id='pose_sitting',evidence=['앉은 자세'],confidence=1)])
    edited = asyncio.run(cc.reference_fallback(memory,edit_job,edit,catalog,ctx))
    assert {t.term_id for t in edited.selections} == {'composition_rule_of_thirds','pose_sitting'}
    result = assemble(asyncio.run(cc.validate(memory,edit_job,edited,catalog,context=ctx)),catalog)
    state = cc.next_state(ctx,edit_job,edited,result,snapshot=catalog)
    remove_job = {'job_id':NEW,'request_text':'삼분할 빼줘'}
    removal = InterpretationOutput(interpretation_state='select_terms',answer_text='삼분할은 빼둘게요.',selections=[],context_updates=[
        dict(role='composition',evidence='삼분할 빼줘',remove_term_ids=['composition_rule_of_thirds'])])
    ctx['state'] = state
    state = cc.next_state(ctx,remove_job,removal,result,snapshot=catalog)
    assert 'composition_rule_of_thirds' not in state['constraints']
    assert state['excluded_conditions']['composition_rule_of_thirds']['source_job_id'] == NEW
    for _ in range(20):
        state = cc.next_state({'state':state},{'job_id':NEW,'request_text':'고마워'},chat(),
            AgentResult(agent_status='drawing_chat',answer_text='좋아요.'),snapshot=catalog)
    ctx['state'] = state; ctx['recent'] = []
    stale = InterpretationOutput(interpretation_state='select_terms',answer_text='찾아요.',selections=[
        dict(role='composition',term_id='composition_rule_of_thirds',evidence=['삼분할 구도'],confidence=1,source_job_id=OLD)])
    with pytest.raises(LLMInvalidStructuredOutput):
        asyncio.run(cc.validate(memory, {'request_text':'찾아줘'},stale,catalog,context=ctx))


def test_worker_twenty_turn_original_topic_add_remove_and_reset(monkeypatch, catalog):
    from backend.services import agent_worker
    from backend.services.conversation_memory import record
    from backend.tests.test_agent_worker import JOB, FakeJobs, FakeRecovery
    from backend.schemas.models import RoutedInterpretation
    from backend.schemas.memory import RecallQuery
    from backend.services.response_assembler import RoleSearchOutcome
    jobs, recovery = FakeJobs(JOB), FakeRecovery()
    ledger = dict(state={'constraints':{}}, rows=[], reads=[], searches=[])
    class Store:
        async def load(self, job):
            return dict(state=deepcopy(ledger['state']), recent=deepcopy(ledger['rows'][-6:]),sources=[],previous_result={})
        async def records(self, job, ids):
            ledger['reads'].append(tuple(map(str,ids)))
            return [r for r in ledger['rows'] if r['job_id'] in set(map(str,ids))]
        async def complete(self, job, result, state):
            ledger['state'] = deepcopy(state)
            ledger['rows'].append(record(dict(job,status='completed',final_payload_json=result.model_dump(mode='json'))))
            await jobs.update_status(job_id=job['job_id'],attempt=job['attempt'],status=agent_worker.JobStatus.COMPLETED,result=result)
    class Adapter:
        async def memory(self,*args,**kwargs):
            return RecallQuery(mode='none')
        async def interpret(self,text,**kwargs):
            if text == '앉은 자세로':
                return InterpretationOutput(interpretation_state='select_terms',answer_text='앉은 자세로 찾아요.',selections=[
                    dict(role='pose',term_id='pose_sitting',evidence=['앉은 자세'],confidence=1)])
            if text == '삼분할 빼줘':
                return InterpretationOutput(interpretation_state='select_terms',answer_text='삼분할은 빼둘게요.',selections=[],context_updates=[
                    dict(role='composition',evidence=text,remove_term_ids=['composition_rule_of_thirds'])])
            return chat()
        async def route_and_interpret(self,text,**kwargs):
            return RoutedInterpretation(route=RecallQuery(mode='none'),interpretation=await self.interpret(text,**kwargs))
    monkeypatch.setattr(agent_worker,'JobRepository',lambda _:jobs)
    monkeypatch.setattr(agent_worker,'JobRetryRecovery',lambda _:recovery)
    monkeypatch.setattr(agent_worker,'ConversationMemory',lambda _:Store())
    worker = agent_worker.AgentJobWorker(object(),catalog,adapter=Adapter())
    async def search(resolution,**kwargs):
        ids = [t.selection.term_id for t in resolution.terms]
        ledger['searches'].append(ids)
        return {t.selection.term_id:RoleSearchOutcome(role=t.selection.role) for t in resolution.terms}
    monkeypatch.setattr(worker,'_search_outcomes',search)
    texts = ['삼분할 구도가 뭐야?'] + ['고마워']*16 + ['그리고 싶어','앉은 자세로','삼분할 빼줘']
    assert len(texts) == 20
    for i,text in enumerate(texts):
        jobs.job = {**JOB,'job_id':f'00000000-0000-4000-8000-{i+1:012d}','request_text':text}
        asyncio.run(worker.run_once())
    assert not recovery.failures
    assert len(ledger['rows']) == 20
    assert ledger['searches'] == [['composition_rule_of_thirds'],['pose_sitting','composition_rule_of_thirds'],['pose_sitting']]
    assert ('00000000-0000-4000-8000-000000000001',) in ledger['reads']
    assert set(ledger['state']['constraints']) == {'pose_sitting'}
    assert 'composition_rule_of_thirds' in ledger['state']['excluded_conditions']
    for i,text in enumerate(['새로 시작하자','그리고 싶어'],100):
        jobs.job = {**JOB,'job_id':f'00000000-0000-4000-8000-{i:012d}','request_text':text}
        asyncio.run(worker.run_once())
    assert ledger['state']['constraints'] == {}
    assert ledger['state']['excluded_conditions'] == {}
    assert ledger['state']['recommendation_group'] is None
    assert len([ids for ids in ledger['searches'] if ids]) == 3


def test_existing_natural_language_aliases_survive_twenty_turns(card_factory, snapshot_factory):
    snapshot = snapshot_factory([card_factory('pose_standing',label_ko='서기',label_en='standing'),
        card_factory('view_three_quarter',role='composition',label_ko='3/4 뷰',label_en='three quarter view')])
    original = row(request='서 있는 캐릭터를 3/4 방향으로 그리고 싶어. 지금은 검색하지 말고 설명해줘.')
    state = cc.next_state(context(),{'job_id':OLD,'request_text':original['request_text']},chat(),
        AgentResult(agent_status='drawing_chat',answer_text='설명해요.'),snapshot=snapshot)
    for _ in range(20):
        state = cc.next_state({'state':state},{'job_id':NEW,'request_text':'고마워'},chat(),
            AgentResult(agent_status='drawing_chat',answer_text='좋아요.'),snapshot=snapshot)
    ctx = context(); ctx['state'] = state
    out = asyncio.run(cc.reference_fallback(Memory([original]),{'job_id':NEW,'request_text':'그리고 싶어'},chat(),snapshot,ctx))
    assert {t.term_id for t in out.selections} == {'pose_standing','view_three_quarter'}


def test_specific_layout_keeps_independent_view_dimension(card_factory, snapshot_factory):
    from backend.services.session_memory import literal_terms
    snap = snapshot_factory([
        card_factory('composition_rule_of_thirds',role='composition',label_ko='삼분할 구도',label_en='rule of thirds'),
        card_factory('layout_composition',role='composition',label_ko='구도',label_en='composition'),
        card_factory('view_front',role='composition',label_ko='정면',label_en='front view')])
    assert set(literal_terms('정면 캐릭터를 삼분할 구도로',snap)) == {'view_front','composition_rule_of_thirds'}


def test_atomic_completion_keeps_topic_fields_and_explicit_null_clears(monkeypatch):
    import json
    from backend.services import conversation_memory as cm
    writes = []
    class Manager:
        async def __aenter__(self): return connection
        async def __aexit__(self,*args): pass
    class Connection:
        def transaction(self): return Manager()
        async def fetchval(self,*args): return NEW
        async def execute(self,sql,*args): writes.append((sql,args))
    connection = Connection()
    class Pool:
        def acquire(self): return Manager()
    class Jobs:
        def __init__(self,connection): pass
        async def update_status(self,**kwargs): pass
    monkeypatch.setattr(cm,'JobRepository',Jobs)
    state = dict(memory_version=1,constraints={},current_topic=None,excluded_conditions={},topic_scope_id=NEW,
        recommendation_topic_scope=None,recommendation_group=None,recommendation_adoption=None,
        recommendation_pending_group_id=None,untrusted_provider_payload='omit')
    asyncio.run(cm.ConversationMemory(Pool()).complete(dict(job_id=NEW,session_id=OLD,attempt=1),
        AgentResult(agent_status='drawing_chat',answer_text='시작해요.'),state))
    saved = json.loads(writes[0][1][1])
    assert saved == {key:value for key,value in state.items() if key != 'untrusted_provider_payload'}
    assert 'recommendation_group' in saved and saved['recommendation_group'] is None


def test_old_source_cannot_cross_scope_on_turn_after_reset(catalog):
    from backend.services.llm import LLMInvalidStructuredOutput
    original = row(request='삼분할 구도로')
    ctx = context(); ctx['state'].update(topic_scope_id=NEW,current_topic=None)
    stale = InterpretationOutput(interpretation_state='select_terms',answer_text='찾아요.',selections=[
        dict(role='composition',term_id='composition_rule_of_thirds',evidence=['삼분할 구도'],confidence=1,source_job_id=OLD)])
    with pytest.raises(LLMInvalidStructuredOutput):
        asyncio.run(cc.validate(Memory([original]), {'request_text':'찾아줘'},stale,catalog,context=ctx))


@pytest.mark.parametrize('role_clear',[False,True])
def test_removing_only_condition_persists_empty_board_across_reload(catalog, role_clear):
    from backend.tests.test_conversation_sessions import database_case
    from backend.services.session_repository import SessionRepository
    from backend.services.job_repository import JobRepository
    from backend.services.agent_worker import AgentJobWorker
    from backend.services.conversation_memory import ConversationMemory
    from backend.schemas.memory import RecallQuery
    from uuid import uuid4
    async def case(pool):
        class Adapter:
            async def memory(self,*args,**kwargs): return RecallQuery(mode='none')
            async def interpret(self,text,**kwargs):
                if text == '삼분할 구도로 찾아줘':
                    return InterpretationOutput(interpretation_state='select_terms',answer_text='삼분할 구도로 찾아요.',selections=[
                        dict(role='composition',term_id='composition_rule_of_thirds',evidence=['삼분할 구도'],confidence=1)])
                if text == '삼분할 빼줘':
                    return InterpretationOutput(interpretation_state='select_terms',answer_text='삼분할은 빼둘게요.',selections=[],context_updates=[
                        dict(role='composition',evidence=text,remove_term_ids=[] if role_clear else ['composition_rule_of_thirds'])])
                return chat()
        session = await SessionRepository(pool).create_session('sole-condition-removal')
        jobs = JobRepository(pool); worker = AgentJobWorker(pool,catalog,adapter=Adapter())
        for text in ['삼분할 구도로 찾아줘','삼분할 빼줘']:
            submitted,_ = await jobs.submit(session_id=session,request_text=text,idempotency_key=str(uuid4()))
            assert await worker.run_once()
        envelope = await jobs.get(session_id=session,job_id=submitted.job_id)
        assert envelope.job_status == 'completed'
        assert envelope.result.agent_status == 'success'
        assert envelope.result.reference_plan.terms == []
        assert envelope.result.reference_update.removed_term_ids == ['composition_rule_of_thirds']
        following,_ = await jobs.submit(session_id=session,request_text='찾아줘',idempotency_key=str(uuid4()))
        job = await jobs.claim_next(); ctx = await ConversationMemory(pool).load(job)
        assert ctx['state']['constraints'] == {}
        assert 'composition_rule_of_thirds' in ctx['state']['excluded_conditions']
        assert ctx['previous_result']['reference_plan']['terms'] == []
        out = await cc.reference_fallback(ConversationMemory(pool),job,chat(),catalog,ctx)
        assert out.selections == []
    asyncio.run(database_case(case))


@pytest.mark.parametrize('text',['새 캐릭터 말고 그대로','"새 캐릭터"라는 말이야'])
def test_model_reset_evidence_cannot_override_negated_or_quoted_user(catalog,text):
    from backend.services.llm import LLMInvalidStructuredOutput
    original,state = explained(catalog); expected = deepcopy(state)
    ctx = context(original); ctx['state'] = state
    output = InterpretationOutput(interpretation_state='drawing_chat',answer_text='이야기해요.',topic_reset_evidence='새 캐릭터')
    with pytest.raises(LLMInvalidStructuredOutput):
        asyncio.run(recommendations.handle(Memory([original]),{'job_id':NEW,'request_text':text},output,catalog,ctx))
    assert ctx['state'] == expected


@pytest.mark.parametrize('text,evidence',[
    ('새 캐릭터 말고 그대로','새 캐릭터 말고 그대로'),
    ('다른 주제로 바꾸지 말고','다른 주제'),
    ('새 캐릭터로 바꾸지 마','새 캐릭터'),
    ('새 캐릭터로 바꾸지마','새 캐릭터')])
def test_reset_guard_uses_whole_current_request_not_model_selected_quote(catalog,text,evidence):
    from backend.services.llm import LLMInvalidStructuredOutput
    original,state = explained(catalog); expected = deepcopy(state)
    ctx = context(original); ctx['state'] = state
    recommendations.reset_context({'job_id':NEW,'request_text':text},ctx)
    assert ctx['state'] == expected

    output = InterpretationOutput(interpretation_state='drawing_chat',answer_text='이야기해요.',topic_reset_evidence=evidence)
    with pytest.raises(LLMInvalidStructuredOutput):
        asyncio.run(recommendations.handle(Memory([original]),{'job_id':NEW,'request_text':text},output,catalog,ctx))
    assert ctx['state'] == expected


@pytest.mark.parametrize('text',[
    '새 캐릭터로 바꿀게. 예전 삼분할은 빼고 정면으로 찾아줘',
    '새 캐릭터로 바꿀게. 정면 구도는 바꾸지 마'])
def test_affirmative_reset_with_independent_exclusion_still_starts_fresh(catalog,text):
    original,state = explained(catalog)
    state['excluded_conditions'] = {'pose_sitting':dict(role='pose',term_id='pose_sitting',evidence='앉은 자세 빼줘',source_job_id=OLD)}
    ctx = context(original); ctx['state'] = state
    recommendations.reset_context({'job_id':NEW,'request_text':text},ctx)
    assert ctx['state']['current_topic'] is None
    assert ctx['state']['excluded_conditions'] == {}
    assert ctx['state']['topic_scope_id'] == NEW


@pytest.mark.parametrize('text',[
    '새 캐릭터가 아니라 기존 캐릭터야',
    "I don't want a new character",
    'I do not want a new character',
    'I don’t want a new character',
    '새 캐릭터는 안 할래',
    '새캐릭터는안할래',
    '새 캐릭터를 원하지 않아',
    '새 캐릭터로 바꾸고 싶지 않아',
    '새 캐릭터라는 말은 무슨 뜻이야?',
    '어제 새 캐릭터로 바꾸자고 했어',
    'What does new character mean?',
    'I said "start over" yesterday',
])
def test_same_clause_reset_negation_and_meta_language_keep_scope(catalog,text):
    from backend.services.session_memory import explicit_reset, reset_is_affirmed
    assert explicit_reset(text) is False
    assert reset_is_affirmed(text,evidence=text) is False
    original,state = explained(catalog); expected=deepcopy(state)
    ctx=context(original); ctx['state']=state
    recommendations.reset_context({'job_id':NEW,'request_text':text},ctx)
    assert ctx['state'] == expected


@pytest.mark.parametrize('text',[
    '새 캐릭터로 바꿀게. 기존 구도는 바꾸지 마',
    '새 캐릭터로 바꿀게. 예전 삼분할 말고 정면으로 찾아줘',
    "Start over. I don't want thirds.",
    "I don't want thirds, but start over with a new character.",
])
def test_reset_consent_is_separate_from_independent_condition_negation(text):
    from backend.services.session_memory import explicit_reset
    assert explicit_reset(text) is True


def test_history_restore_uses_latest_empty_board_instead_of_prior_reference():
    from backend.tests.test_conversation_sessions import database_case
    from backend.services.session_repository import SessionRepository
    from backend.services.job_repository import JobRepository
    from uuid import uuid4
    import json

    async def case(pool):
        session = await SessionRepository(pool).create_session('empty-board-history')
        jobs = JobRepository(pool)
        first, _ = await jobs.submit(session_id=session, request_text='rule of thirds', idempotency_key=str(uuid4()))
        cleared, _ = await jobs.submit(session_id=session, request_text='remove thirds', idempotency_key=str(uuid4()))
        reference = AgentResult(agent_status='success', reference_plan={'terms': [{
            'role': 'composition', 'term_id': 'composition_rule_of_thirds',
            'label_ko': 'rule of thirds', 'label_en': 'rule of thirds',
            'plain_meaning_ko': 'rule of thirds', 'search_url': 'https://www.pinterest.com/search/pins/?q=rule%20of%20thirds',
            'pins': [], 'reason_codes': [],
        }], 'unresolved_roles': []})
        empty = AgentResult(agent_status='success', reference_plan={'terms': [], 'unresolved_roles': []})
        await pool.execute("UPDATE jobs SET status='completed',succeeded=true,final_payload_json=$2::jsonb,created_at=now()-interval '1 second' WHERE job_id=$1::uuid",
                           first.job_id, json.dumps(reference.model_dump(mode='json')))
        await pool.execute("UPDATE jobs SET status='completed',succeeded=true,final_payload_json=$2::jsonb,created_at=now() WHERE job_id=$1::uuid",
                           cleared.job_id, json.dumps(empty.model_dump(mode='json')))

        page = await jobs.history_page(session)
        assert page['reference_item']['job_id'] == cleared.job_id
        assert page['reference_item']['result']['reference_plan']['terms'] == []
        assert page['previous_reference_item']['job_id'] == first.job_id

    asyncio.run(database_case(case))


def test_server_confirmed_topic_reset_is_exposed_as_a_gallery_clear_event(catalog):
    from backend.tests.test_conversation_sessions import database_case
    from backend.services.session_repository import SessionRepository
    from backend.services.job_repository import JobRepository
    from backend.services.agent_worker import AgentJobWorker
    from backend.schemas.memory import RecallQuery
    from uuid import uuid4

    async def case(pool):
        class Adapter:
            async def memory(self, *args, **kwargs):
                return RecallQuery(mode='none')

            async def interpret(self, *args, **kwargs):
                return chat()

        session = await SessionRepository(pool).create_session('topic-reset-gallery')
        jobs = JobRepository(pool)
        reset, _ = await jobs.submit(session_id=session, request_text='start over with a new character',
                                     idempotency_key=str(uuid4()))
        worker = AgentJobWorker(pool, catalog, adapter=Adapter())
        assert await worker.run_once()

        envelope = await jobs.get(session_id=session, job_id=reset.job_id)
        assert envelope.result.context_reset is True
        page = await jobs.history_page(session)
        assert page['reference_item']['job_id'] == reset.job_id
        assert page['reference_item']['result']['context_reset'] is True

    asyncio.run(database_case(case))


@pytest.mark.parametrize('role_clear', [False, True])
def test_removing_an_unconfirmed_discussion_topic_prevents_later_adoption(catalog, role_clear):
    original, state = explained(catalog)
    ctx = context(original)
    ctx['state'] = state
    removal_job = {'job_id': NEW, 'request_text': 'remove the rule of thirds'}
    removal = InterpretationOutput(interpretation_state='select_terms', answer_text='Removed.', selections=[],
        context_updates=[dict(role='composition', evidence='remove the rule of thirds',
                              remove_term_ids=[] if role_clear else ['composition_rule_of_thirds'])])
    empty = AgentResult(agent_status='success', reference_plan={'terms': [], 'unresolved_roles': []})

    resolution = asyncio.run(cc.validate(Memory([original]), removal_job, removal, catalog, context=ctx))
    assert resolution.status == 'proceed' and resolution.terms == []
    state = cc.next_state(ctx, removal_job, removal, empty, snapshot=catalog)
    assert not (state.get('current_topic') or {}).get('terms')
    assert state['excluded_conditions']['composition_rule_of_thirds']['source_job_id'] == NEW

    ctx['state'] = state
    out = asyncio.run(cc.reference_fallback(Memory([original]), {'job_id': NEW, 'request_text': 'find it'}, chat(), catalog, ctx))
    assert out.selections == []


def test_legacy_bare_desire_retry_skips_its_empty_clarification_and_reuses_the_prior_topic(catalog):
    original = row(request='what is rule of thirds?', message='rule of thirds explanation')
    clarification = dict(job_id=NEW, request_text='\uadf8\ub9ac\uace0 \uc2f6\uc5b4', terms=[],
                         question='Which pose?', message='')
    ctx = context()
    ctx['recent'] = [original, clarification]
    memory = Memory([original])

    out = asyncio.run(cc.reference_fallback(memory,
        {'job_id': '00000000-0000-4000-8000-000000000021', 'request_text': '\uadf8\ub9ac\uace0 \uc2f6\uc5b4'},
        chat(), catalog, ctx))

    assert [item.term_id for item in out.selections] == ['composition_rule_of_thirds']
    assert memory.reads and all(ids == (OLD,) for ids in memory.reads)
