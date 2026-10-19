import asyncio
import json
from types import SimpleNamespace
import pytest
from pydantic import ValidationError
from backend.schemas import models
from backend.services import structured_output
from backend.tests.test_agent_worker import FakeJobs, FakeRecovery, FakeAdapter, _worker


def test_envelope_contract():
    assert hasattr(models, 'RoutedInterpretation')
    model = models.RoutedInterpretation
    for mode, action in [('none', 'update'), ('recall', 'update'), ('mixed', 'update'), ('none', 'refresh_all')]:
        payload = {'route': {'mode': mode, 'reference_action': action}, 'interpretation': None}
        if mode == 'none' and action == 'update':
            with pytest.raises(ValidationError): model.model_validate(payload)
        else: assert model.model_validate(payload).interpretation is None


def test_envelope_schema_refs_and_catalog():
    assert hasattr(structured_output, 'routed_response_format')
    schema = structured_output.routed_response_format(json.dumps({'active_cards':[{'role':'pose','term_id':'pose_shift'}]}))['json_schema']['schema']
    def visit(node):
        if isinstance(node, dict):
            if '$ref' in node:
                target = schema
                for part in node['$ref'][2:].split('/'): target = target[part]
            if node.get('type') == 'object':
                assert set(node['required']) == set(node['properties'])
                assert node['additionalProperties'] is False
            for value in node.values(): visit(value)
        elif isinstance(node, list):
            for value in node: visit(value)
    visit(schema)
    assert schema['$defs']['InterpretationSelection_pose']['properties']['term_id']['enum'] == ['pose_shift']


def test_combined_worker_skips_legacy_calls(monkeypatch, snapshot_factory, card_factory):
    jobs, recovery = FakeJobs(), FakeRecovery()
    class Combined(FakeAdapter):
        combined = []
        async def route_and_interpret(self, request_text, **kwargs):
            self.combined.append(kwargs)
            return SimpleNamespace(route=__import__('backend.schemas.memory', fromlist=['RecallQuery']).RecallQuery(mode='none'), interpretation=self.output)
        async def memory(self, *args, **kwargs): pytest.fail('classify called')
        async def interpret(self, *args, **kwargs): pytest.fail('interpret called')
    adapter = Combined()
    worker = _worker(monkeypatch, jobs, recovery, snapshot_factory([card_factory('pose_shift',role='pose')]), adapter)
    asyncio.run(worker.run_once())
    assert len(adapter.combined) == 1
    assert not recovery.failures
    assert jobs.writes[-1][1] is not None

from copy import deepcopy
from contextlib import nullcontext
from pathlib import Path
from uuid import uuid4
from backend.schemas.memory import RecallQuery, RecallAnswer, ContextUpdate, NO_RECORDS, TOO_MANY
from backend.schemas.models import InterpretationOutput, RoutedInterpretation
from backend.schemas.enums import AgentStatus, JobStatus
from backend.services.llm import LLMInvalidStructuredOutput
from backend.services.response_assembler import RoleSearchOutcome
from backend.tests.test_reference_update import prior, pin
from backend.tests.test_agent_worker import JOB


def selection(term_id='pose_shift', role='pose', evidence='change', **extra):
    return dict(role=role, term_id=term_id, evidence=[evidence], confidence=1, **extra)


def output(selections=None, **extra):
    return InterpretationOutput(interpretation_state='select_terms',
        selections=selections or [selection()], answer_text='설명입니다.', **extra)


class CombinedAdapter(FakeAdapter):
    def __init__(self, query, interpretation=None, *, error=None, answer=None):
        super().__init__(interpretation)
        self.query, self.combined_error = query, error
        self.answer = answer
        self.events, self.inputs = [], []

    async def route_and_interpret(self, request_text, **kwargs):
        self.events.append('combined')
        self.inputs.append(deepcopy(kwargs))
        if self.combined_error: raise self.combined_error
        return RoutedInterpretation(route=self.query, interpretation=self.output
            if self.query.mode == 'none' and self.query.reference_action == 'update' else None)

    async def memory(self, operation, data, *args, **kwargs):
        assert operation == 'answer'
        self.events.append('answer')
        return self.answer

    async def interpret(self, request_text, **kwargs):
        self.events.append('interpret')
        self.calls.append(deepcopy(kwargs))
        return self.output


def combined_case(monkeypatch, snapshot_factory, card_factory, adapter, *, context=None,
                  request='change', cards=None, records=None, originals=None):
    jobs, recovery = FakeJobs({**JOB, 'request_text': request}), FakeRecovery()
    snapshot = snapshot_factory(cards or [card_factory('pose_shift')])
    worker = _worker(monkeypatch, jobs, recovery, snapshot, adapter)
    context = deepcopy(context or {'state':{}, 'recent':[], 'sources':[]})
    searches, completed = [], []
    async def load(job): return context
    async def search(job, query):
        adapter.events.append('retrieve')
        assert job['session_id'] == JOB['session_id']
        return records or []
    async def original_records(job, ids): return originals or []
    async def complete(job, result, state):
        completed.append((result, state))
        await jobs.update_status(job_id=job['job_id'],attempt=job['attempt'], status=JobStatus.COMPLETED,result=result)
    async def search_outcomes(resolution, **kwargs):
        searches.append(([term.selection.term_id for term in resolution.terms], kwargs))
        return {term.selection.term_id: RoleSearchOutcome(role=term.selection.role,
            pins=[pin('999')]) for term in resolution.terms}
    worker._memory.load, worker._memory.search = load, search
    worker._memory.records, worker._memory.complete = original_records, complete
    worker._search_outcomes = search_outcomes
    asyncio.run(worker.run_once())
    return SimpleNamespace(jobs=jobs, recovery=recovery, context=context, searches=searches, completed=completed)


def test_combined_selective_same_role_preserves_pins_and_constraints(monkeypatch, snapshot_factory, card_factory):
    previous = prior()
    previous['reference_plan']['terms'].append({**previous['reference_plan']['terms'][1], 'term_id':'pose_aim', 'pins':[pin('33').model_dump(mode='json')]})
    context={'state':{'constraints':{'pose_standing':{'role':'pose','term_id':'pose_standing','evidence':'old'}}}, 'recent':[], 'sources':[], 'previous_result':previous}
    adapter=CombinedAdapter(RecallQuery(mode='none'),output([selection('pose_shift')],
        context_updates=[ContextUpdate(role='pose',term_id='pose_shift',remove_term_ids=['pose_standing'], evidence='change')]))
    case=combined_case(monkeypatch,snapshot_factory,card_factory,adapter,context=context,
        cards=[card_factory(t,role=r) for r,t in [('body','body_slim'),('pose','pose_standing'),('pose','pose_aim'),('pose','pose_shift')]])
    assert not case.recovery.failures
    result,state=case.completed[0]
    assert adapter.events == ['combined']
    assert case.searches[0][0] == ['pose_shift']
    assert [t.term_id for t in result.reference_plan.terms] == ['body_slim','pose_aim','pose_shift']
    assert result.reference_plan.terms[1].pins[0].pin_id == '33'
    assert result.reference_update.removed_term_ids == ['pose_standing']
    assert result.reference_update.replaced_term_ids == ['pose_shift']
    assert set(result.reference_update.preserved_term_ids) == {'body_slim','pose_aim'}
    assert set(state['constraints']) == {'pose_shift'}
    assert len(adapter.inputs[0]['current_reference_terms']) == 3


@pytest.mark.parametrize('clarify', [False, True])
def test_combined_pending_reply_and_ambiguity(monkeypatch,snapshot_factory,card_factory,clarify):
    question='어떤 자세인가요?'
    interpretation=InterpretationOutput(interpretation_state='needs_clarification',unresolved_constraints=['자세'],
        clarifying_question='어느 방향인가요?',clarification_type='insufficient_visual_evidence') if clarify else output()
    adapter=CombinedAdapter(RecallQuery(mode='none'),interpretation)
    context={'state':{'pending_question':question,'constraints':{}},'recent':[],'sources':[]}
    case=combined_case(monkeypatch,snapshot_factory,card_factory,adapter,context=context)
    assert not case.recovery.failures
    assert adapter.events == ['combined']
    assert adapter.inputs[0]['session_context']['pending_question'] == question
    assert case.completed[0][1]['pending_question'] == ('어느 방향인가요?' if clarify else None)


@pytest.mark.parametrize('action,targets,expected',[
    ('refresh_all',{},['body_slim','pose_standing']),
    ('refresh_roles',{'refresh_roles':['pose']},['pose_standing']),
    ('refresh_terms',{'refresh_term_ids':['pose_standing']},['pose_standing']),
    ('refresh_terms',{'refresh_term_ids':[]},[]),
    ('refresh_terms',{'refresh_term_ids':['unknown']},[]),
    ('refresh_roles',{'refresh_roles':['view']},[]),
])
def test_combined_refresh_scopes(monkeypatch,snapshot_factory,card_factory,action,targets,expected):
    adapter=CombinedAdapter(RecallQuery(mode='none',reference_action=action,**targets))
    context={'state':{'constraints':{}},'recent':[],'sources':[],'previous_result':prior()}
    case=combined_case(monkeypatch,snapshot_factory,card_factory,adapter,context=context,
        cards=[card_factory('body_slim',role='body'),card_factory('pose_standing')])
    assert not case.recovery.failures
    assert adapter.events == ['combined']
    assert case.searches[0][0] == expected
    result=case.completed[0][0]
    if expected:
        assert result.reference_update.replaced_term_ids == expected
        assert case.searches[0][1]['exclude_pin_ids'] == {'body_slim':['11'],'pose_standing':['22']}
    else: assert result.agent_status is AgentStatus.NEEDS_CLARIFICATION


@pytest.mark.parametrize('mode', ['recall','mixed'])
@pytest.mark.parametrize('count', [0,1,21])
def test_combined_recall_and_mixed_order(monkeypatch,snapshot_factory,card_factory,mode,count):
    record={'job_id':str(uuid4()),'request_text':'old change', 'terms':[]}
    records=[record] if count == 1 else [dict(record,job_id=str(uuid4())) for _ in range(count)]
    adapter=CombinedAdapter(RecallQuery(mode=mode),output(),answer=RecallAnswer(answer='이전 답변',citations=[{'job_id':record['job_id'],'quote':'old change'}]))
    case=combined_case(monkeypatch,snapshot_factory,card_factory,adapter,records=records)
    assert not case.recovery.failures
    expected=['combined','retrieve']+(['answer'] if count==1 else [])+(['interpret'] if mode=='mixed' else [])
    assert adapter.events == expected
    result,state=case.completed[0]
    assert result.memory_answer == ('이전 답변' if count==1 else NO_RECORDS if count==0 else TOO_MANY)
    if mode=='mixed' and count==1:
        assert adapter.calls[0]['session_context']['sources'] == [record]
        assert adapter.inputs[0]['session_context']['sources'] == []
        assert str(result.sources[0].job_id) == record['job_id']
    if mode=='recall':
        assert not case.searches
        assert state == {}


@pytest.mark.parametrize('bad', ['quote','foreign'])
def test_combined_recall_rejects_invalid_original_citations(monkeypatch,snapshot_factory,card_factory,bad):
    record={'job_id':str(uuid4()),'request_text':'old request','terms':[]}
    adapter=CombinedAdapter(RecallQuery(mode='recall',reference_action='refresh_all'),answer=RecallAnswer(answer='답변',citations=[{
        'job_id':str(uuid4()) if bad=='foreign' else record['job_id'], 'quote':'invented' if bad=='quote' else 'old request'}]))
    case=combined_case(monkeypatch,snapshot_factory,card_factory,adapter,records=[record])
    assert case.recovery.failures and not case.completed and not case.searches
    assert case.context['reference_action'] == 'update'


@pytest.mark.parametrize('fault',['source','evidence','term','removal','invalid_envelope'])
def test_combined_invalid_output_never_falls_back(monkeypatch,snapshot_factory,card_factory,fault):
    selected=selection(term_id='unknown' if fault=='term' else 'pose_shift',evidence='invented' if fault=='evidence' else 'change',
        **({'source_job_id':uuid4()} if fault=='source' else {}))
    result=output([selected],context_updates=[ContextUpdate(role='pose',term_id='pose_shift',remove_term_ids=['unknown'],evidence='change')] if fault=='removal' else [])
    adapter=CombinedAdapter(RecallQuery(mode='none'),result,error=LLMInvalidStructuredOutput('invalid') if fault=='invalid_envelope' else None)
    case=combined_case(monkeypatch,snapshot_factory,card_factory,adapter)
    assert adapter.events == ['combined']
    assert case.recovery.failures and not case.completed and not case.searches


@pytest.mark.parametrize('mode,action', [('recall','update'),('mixed','update'),('none','refresh_terms')])
def test_envelope_rejects_eager_interpretation(mode,action):
    with pytest.raises(ValidationError):
        RoutedInterpretation(route=RecallQuery(mode=mode,reference_action=action),interpretation=output())


@pytest.mark.parametrize('fault',['unknown','duplicate','state'])
def test_envelope_rejects_nested_invalid_output(fault):
    data=output().model_dump(mode='json')
    if fault=='unknown': data['unknown']='secret'
    if fault=='duplicate': data['selections']*=2
    if fault=='state': data['unresolved_constraints']=['conflict']
    with pytest.raises(ValidationError): RoutedInterpretation.model_validate({'route':{'mode':'none'},'interpretation':data})


def codex_adapter(monkeypatch,payload):
    from backend.services.codex_llm import CodexInterpretationAdapter
    import backend.services.llm as llm
    monkeypatch.setattr(llm.openai,'AsyncOpenAI',lambda **kw: pytest.fail('OpenRouter constructed'))
    settings=SimpleNamespace(interpreter_prompt_version='uhkegryo-interpreter-v4',codex_timeout_seconds=10)
    adapter=CodexInterpretationAdapter(settings=settings,system_message='nested rules',user_template='{{request_text}} {{active_cards_json}}')
    monkeypatch.setattr(adapter,'_resolve_prompt_path',lambda:Path(__file__).parents[2]/'prompts/uhkegryo-interpreter-v4.md')
    calls=[]
    async def generate(settings,messages,schema):
        calls.append((messages,schema))
        return payload
    adapter._generate=generate
    return adapter,calls


@pytest.mark.parametrize('action,targets',[('update',{}),('refresh_terms',{'refresh_term_ids':['pose_shift']})])
def test_codex_combined_one_generate_normalizes_filters_and_retains_inputs(monkeypatch,action,targets):
    payload={'route':{'mode':'none','reference_action':action,**targets,'start':'invalid date','keywords':['']},
        'interpretation':output().model_dump(mode='json') if action=='update' else None}
    adapter,calls=codex_adapter(monkeypatch,json.dumps(payload))
    result=asyncio.run(adapter.route_and_interpret('request-marker',active_cards_json=json.dumps({'active_cards':[{'role':'pose','term_id':'pose_shift'}]}),
        session_context={'pending_question':'pending-marker'},current_reference_terms=[{'term_id':'existing-marker'}],
        current_reference_roles=['pose'],validation_feedback=[{'code':'term_duplicate'}]))
    assert len(calls)==1
    messages,schema=calls[0]
    text=json.dumps(messages,ensure_ascii=False)
    for marker in ['request-marker','pending-marker','existing-marker','term_duplicate','pose_shift']: assert marker in text
    assert result.route.start is None and result.route.keywords == []
    assert result.route.refresh_term_ids == targets.get('refresh_term_ids',[])
    assert schema['properties']['route']['$ref'] == '#/$defs/RecallQuery'


@pytest.mark.parametrize('payload',['raw private secret', '{"route":{"mode":"none","unknown":"private secret"},"interpretation":null}'])
def test_codex_combined_invalid_once_with_safe_diagnostics(monkeypatch,payload):
    adapter,calls=codex_adapter(monkeypatch,payload)
    with pytest.raises(LLMInvalidStructuredOutput) as caught:
        asyncio.run(adapter.route_and_interpret('request'))
    assert len(calls)==1
    assert 'private secret' not in str(caught.value)
    assert 'private secret' not in json.dumps(caught.value.feedback)

@pytest.mark.parametrize('count',[10,11])
def test_combined_mixed_categories_card_limit_before_search(monkeypatch,snapshot_factory,card_factory,count):
    categories=['pose']*5+['composition']*5
    selected=[selection(f'{role}_{i}',role=role) for i,role in enumerate(categories)]
    context={'state':{},'recent':[],'sources':[]}
    cards=[card_factory(item['term_id'],role=item['role']) for item in selected]
    if count==11:
        # Existing card plus ten independent model selections must fail before search/save.
        previous=prior()
        previous['reference_plan']['terms']=previous['reference_plan']['terms'][:1]
        context['previous_result']=previous
        cards.append(card_factory('body_slim',role='body'))
    adapter=CombinedAdapter(RecallQuery(mode='none'),output(selected))
    case=combined_case(monkeypatch,snapshot_factory,card_factory,adapter,context=context,cards=cards)
    if count==10:
        assert not case.recovery.failures
        assert [term.role.value for term in case.completed[0][0].reference_plan.terms] == categories
        assert len(case.searches[0][0]) == 10
    else: assert case.recovery.failures and not case.completed and not case.searches


@pytest.mark.parametrize('empty',[False,True])
def test_combined_mixed_refresh_defers_to_trusted_board(monkeypatch,snapshot_factory,card_factory,empty):
    record={'job_id':str(uuid4()),'request_text':'old request','terms':[]}
    adapter=CombinedAdapter(RecallQuery(mode='mixed',reference_action='refresh_terms',refresh_term_ids=['pose_standing']),
        answer=RecallAnswer(answer='이전 답변',citations=[{'job_id':record['job_id'],'quote':'old request'}]))
    context={'state':{'pending_question':None},'recent':[],'sources':[],'previous_result':prior()}
    case=combined_case(monkeypatch,snapshot_factory,card_factory,adapter,context=context,
        cards=[card_factory('body_slim',role='body'),card_factory('pose_standing')],records=[] if empty else [record])
    assert not case.recovery.failures
    assert adapter.events == ['combined','retrieve']+([] if empty else ['answer'])
    assert case.searches[0][0] == ['pose_standing']
    result,state=case.completed[0]
    assert [term.term_id for term in result.reference_plan.terms] == ['body_slim','pose_standing']
    assert result.reference_plan.terms[0].pins[0].pin_id=='11'
    assert state == context['state']


def test_combined_clear_new_request_retains_direct_interpret(monkeypatch,snapshot_factory,card_factory):
    request='Find character pose references'
    adapter=CombinedAdapter(RecallQuery(mode='none'),output([selection(evidence=request)]))
    case=combined_case(monkeypatch,snapshot_factory,card_factory,adapter,request=request)
    assert not case.recovery.failures
    assert adapter.events==['interpret']


def test_combined_repeated_ambiguity_uses_existing_guidance(monkeypatch,snapshot_factory,card_factory):
    question='어떤 자세인가요?'
    adapter=CombinedAdapter(RecallQuery(mode='none'),InterpretationOutput(interpretation_state='needs_clarification',
        unresolved_constraints=['자세'],clarifying_question=question,clarification_type='insufficient_visual_evidence'))
    case=combined_case(monkeypatch,snapshot_factory,card_factory,adapter,
        context={'state':{'pending_question':question,'constraints':{}},'recent':[],'sources':[]})
    assert not case.recovery.failures
    result,state=case.completed[0]
    assert result.agent_status is AgentStatus.REFERENCE_GUIDANCE
    assert state['pending_question'] is None


def test_combined_refresh_inactive_scope_does_not_expand(monkeypatch,snapshot_factory,card_factory):
    adapter=CombinedAdapter(RecallQuery(mode='none',reference_action='refresh_terms',refresh_term_ids=['pose_standing']))
    case=combined_case(monkeypatch,snapshot_factory,card_factory,adapter,
        context={'state':{},'recent':[],'sources':[],'previous_result':prior()},
        cards=[card_factory('body_slim',role='body')])
    assert not case.recovery.failures
    assert case.completed[0][0].agent_status is AgentStatus.NEEDS_CLARIFICATION
    assert case.searches[0][0]==[]
