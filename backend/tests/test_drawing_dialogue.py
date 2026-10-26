"""Drawing chat uses the existing interpreter without reference/provider side effects."""
import asyncio
from copy import deepcopy
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from backend.schemas.models import AgentResult, InterpretationOutput, RoutedInterpretation
from backend.schemas.memory import RecallQuery
from backend.services import agent_worker, conversation_context
from backend.services.conversation_memory import record
from backend.services.resolver import resolve
from backend.services.response_assembler import assemble, RoleSearchOutcome
from backend.tests.test_agent_worker import FakeJobs, FakeRecovery
from backend.tests.test_llm_adapter import _adapter, _FakeCompletions, _FakeResponse
from pathlib import Path
import json


def chat(text='둥근 강아지의 실루엣부터 가볍게 그려 보세요.'):
    return InterpretationOutput(interpretation_state='drawing_chat', answer_text=text)


def out_of_scope():
    return InterpretationOutput(interpretation_state='out_of_scope')


def test_out_of_scope_has_a_distinct_interpreter_to_api_contract(snapshot_factory):
    output = out_of_scope()
    resolution = resolve(output, snapshot_factory([]), request_text='파이썬 정렬 함수를 짜줘')
    assert resolution.status == 'out_of_scope' and not resolution.terms
    result = assemble(resolution, snapshot_factory([]), answer_text=output.answer_text)
    assert result.agent_status == 'out_of_scope'
    assert result.reason_codes == ['OUT_OF_SCOPE_REQUEST']
    assert result.reference_plan is None and result.clarifying_question is None
    assert '캐릭터' in result.user_message and '레퍼런스' in result.user_message


@pytest.mark.parametrize('extra', [
    {'answer_text':'파이썬 코드는 이렇게 작성하세요.'},
    {'clarifying_question':'무엇을 도와드릴까요?'},
    {'clarification_type':'abstract_intent'},
    {'unresolved_constraints':['서비스 범위 밖']},
    {'context_updates':[{'role':'pose','term_id':'pose_sitting','evidence':'앉은'}]},
    {'selections':[{'role':'pose','term_id':'pose_sitting','evidence':['앉은'],'confidence':1}]},
])
def test_out_of_scope_interpretation_cannot_leak_content_or_create_conditions(extra):
    with pytest.raises(ValidationError):
        InterpretationOutput.model_validate({
            'interpretation_state':'out_of_scope',
            'answer_text':'',
            **extra,
        })


def test_adapter_prompt_accepts_structured_out_of_scope_without_retry():
    transport = _FakeCompletions([_FakeResponse(json.dumps(
        out_of_scope().model_dump(mode='json'), ensure_ascii=False
    ))])
    adapter = _adapter(transport)
    output = asyncio.run(adapter.interpret(
        '내일 서울 날씨를 알려줘',
        job_id='outside', session_id='synthetic', attempt=1, max_attempts=3,
    ))
    assert output.interpretation_state == 'out_of_scope'
    assert len(transport.calls) == 1
    assert 'interpretation_state=out_of_scope' in transport.calls[0]['messages'][0]['content']


def test_chat_has_its_own_contract_and_no_catalog_requirements(snapshot_factory):
    output = chat('동그라미를 조합해 앉은 강아지의 러프부터 시작할 수 있어요.')
    resolution = resolve(output, snapshot_factory([]), request_text='뭘 그리지?')
    assert resolution.status == 'chat' and not resolution.terms
    result = assemble(resolution, snapshot_factory([]), answer_text=output.answer_text)
    assert result.agent_status == 'drawing_chat' and result.answer_text == output.answer_text
    assert result.reference_plan is None and result.clarifying_question is None and not result.reason_codes


@pytest.mark.parametrize('extra', [
    {'answer_text':''}, {'clarifying_question':'어떤 포즈인가요?'},
    {'clarification_type':'abstract_intent'}, {'unresolved_constraints':['체형 없음']},
    {'context_updates':[{'role':'pose','term_id':'pose_sitting','evidence':'앉은'}]},
    {'selections':[{'role':'pose','term_id':'pose_sitting','evidence':['앉은'],'confidence':1}]},
])
def test_chat_cannot_silently_create_reference_conditions(extra):
    with pytest.raises(ValidationError):
        InterpretationOutput.model_validate({'interpretation_state':'drawing_chat','answer_text':'그림 이야기예요.',**extra})


@pytest.mark.parametrize('extra', [{'answer_text':''},{'clarifying_question':'체형은요?'},
    {'reason_codes':['INSUFFICIENT_VISUAL_EVIDENCE']},{'reference_plan':{'terms':[]}}])
def test_chat_result_requires_text_without_search_or_question(extra):
    with pytest.raises(ValidationError):
        AgentResult.model_validate({'agent_status':'drawing_chat','answer_text':'그림 이야기예요.',**extra})


def test_bounded_assistant_chat_is_available_to_short_followups():
    row={'status':'completed','job_id':'previous','request_text':'뭘 그리지?',
         'final_payload_json':{'agent_status':'drawing_chat','answer_text':'둥근 강아지를 작게 스케치해 보세요.'}}
    remembered=record(row)
    assert remembered['message']=='둥근 강아지를 작게 스케치해 보세요.'
    assert remembered['terms']==[] and not remembered['question']
    row['final_payload_json']['answer_text']='가'*4000
    assert len(record(row)['message'])<=1000
    row['final_payload_json']['agent_status']='unsafe_input'
    assert not record(row)['message'] and not record(row)['request_text']


def test_chat_followup_then_explicit_reference_uses_context_and_searches_once(monkeypatch, snapshot_factory, card_factory):
    initial={'constraints':{},'pending_question':None}
    memory=SimpleNamespace(state=deepcopy(initial),recent=[],results=[])
    jobs=FakeJobs({'job_id':'chat-1','session_id':'s','request_text':'뭘 그리지?','attempt':1,'max_attempts':1})
    recovery=FakeRecovery()
    class Memory:
        async def load(self,job):
            return {'state':deepcopy(memory.state),'recent':deepcopy(memory.recent),'sources':[]}
        async def complete(self,job,result,state):
            memory.state=deepcopy(state);memory.results.append(result)
            memory.recent.append(record({'job_id':job['job_id'],'request_text':job['request_text'],
                'status':'completed','final_payload_json':result.model_dump(mode='json')}))
            await jobs.update_status(job_id=job['job_id'],attempt=1,status=agent_worker.JobStatus.COMPLETED,result=result)
    calls=[]
    class Adapter:
        async def route_and_interpret(self,text,**kwargs):
            calls.append((text,kwargs['session_context']))
            output=chat('둥근 강아지를 작게 스케치해 보세요.') if text=='뭘 그리지?' else (
                chat('앞서 말한 강아지는 머리와 몸을 원 두 개로 단순화해 보세요.') if text=='더 쉽게' else
                InterpretationOutput(interpretation_state='select_terms',answer_text='앉은 자세에서는 엉덩이와 바닥의 접점을 확인해 보세요.',
                    selections=[{'role':'pose','term_id':'pose_sitting','evidence':['앉은'],'confidence':1}],
                    context_updates=[{'role':'pose','term_id':'pose_sitting','evidence':'앉은'}]))
            return RoutedInterpretation(route=RecallQuery(mode='none'),interpretation=output)
        async def interpret(self,*a,**kw):raise AssertionError('combined interpreter must not be repeated')
        async def memory(self,*a,**kw):raise AssertionError('ordinary chat must not execute record recall')
    monkeypatch.setattr(agent_worker,'JobRepository',lambda _:jobs)
    monkeypatch.setattr(agent_worker,'JobRetryRecovery',lambda _:recovery)
    monkeypatch.setattr(agent_worker,'ConversationMemory',lambda _:Memory())
    worker=agent_worker.AgentJobWorker(object(),snapshot_factory([card_factory('pose_sitting')]),adapter=Adapter())
    searches=[]
    async def search(resolution,**kwargs):
        searches.append(resolution)
        return {'pose_sitting':RoleSearchOutcome(role='pose')}
    monkeypatch.setattr(worker,'_search_outcomes',search)
    for i,text in enumerate(['뭘 그리지?','더 쉽게','그 앉은 자세 레퍼런스 찾아줘']):
        jobs.job={**jobs.job,'job_id':f'turn-{i}','request_text':text}
        asyncio.run(worker.run_once())
        if i<2:assert not searches and memory.state==initial
    assert [r.agent_status.value for r in memory.results]==['drawing_chat','drawing_chat','success']
    assert calls[1][1]['recent'][0]['message']=='둥근 강아지를 작게 스케치해 보세요.'
    assert len(calls)==3 and len(searches)==1 and not recovery.failures
    assert 'pose_sitting' in memory.state['constraints']


def test_chat_preserves_existing_constraints_and_pending_question():
    before={'constraints':{'pose_sitting':{'role':'pose','term_id':'pose_sitting','evidence':'앉은','source_job_id':'old'}},
            'pending_question':'오른손은 어디를 향하나요?'}
    output=chat('손 연습이 답답할 때는 실루엣부터 단순하게 잡아 보세요.')
    result=AgentResult(agent_status='drawing_chat',answer_text=output.answer_text)
    assert conversation_context.next_state({'state':before},{'job_id':'new'},output,result)==before


def test_existing_adapter_sends_dialogue_rules_context_and_accepts_chat():
    transport = _FakeCompletions([_FakeResponse(json.dumps(chat().model_dump(mode='json'), ensure_ascii=False))])
    adapter = _adapter(transport)
    context = {'recent':[{'job_id':'old', 'request_text':'뭘 그리지?', 'message':'둥근 고양이를 그려 봐요.'}],
               'constraints':{}, 'pending_question':None, 'sources':[]}
    output = asyncio.run(adapter.interpret('더 쉽게', job_id='j', session_id='s', attempt=1,
        max_attempts=1, session_context=context))
    assert output.interpretation_state == 'drawing_chat'
    messages = transport.calls[0]['messages']
    assert 'interpretation_state=drawing_chat' in messages[0]['content']
    assert 'genuinely missing' in messages[0]['content']
    assert '둥근 고양이' in messages[1]['content'] and '더 쉽게' in messages[1]['content']
    root = Path(__file__).resolve().parents[2]
    assert 'COPY skills/drawing-dialogue/SKILL.md /app/skills/drawing-dialogue/SKILL.md' in (root/'Dockerfile').read_text(encoding='utf-8')


@pytest.mark.parametrize('request_text', [
    '뭐 그릴까?', '캐릭터 아이디어 추천해줘', '어떤 자세로 그릴지 잘 모르겠어',
    '캐릭터에 어울리는 배경과 소품을 추천해줘', '앉아 있는 캐릭터 레퍼런스를 찾아줘',
])
def test_all_interpreter_intents_receive_character_scope_before_untrusted_context(request_text):
    transport = _FakeCompletions([_FakeResponse(json.dumps(chat().model_dump(mode='json'), ensure_ascii=False))])
    adapter = _adapter(transport)
    asyncio.run(adapter.interpret(request_text, job_id='scope', session_id='synthetic', attempt=1,
        max_attempts=1, session_context={'recent':[{'job_id':'synthetic-old','message':'창가와 우산을 더해 보세요.'}]}))
    system, user = transport.calls[0]['messages'][:2]
    assert system['role'] == 'system'
    assert 'CHARACTER-FOCUSED SERVICE SCOPE' in system['content']
    assert 'Never proactively suggest or introduce props, background objects, scenery, locations or scene dressing' in system['content']
    assert 'Preserve explicit user posture requirements' in system['content']
    assert 'clarifying_question' in system['content']
    assert 'ordinary drawing worries' in system['content']
    assert '창가와 우산' in user['content']


def test_combined_route_uses_same_character_scope_for_short_followups():
    from backend.services.codex_llm import CodexInterpretationAdapter
    from backend.shared.config import Settings
    adapter = CodexInterpretationAdapter(settings=Settings(_env_file=None,
        database_url='sqlite:///./scope-test.db', interpreter_prompt_version='uhkegryo-interpreter-v4',
        interpreter_prompt_path=str(Path(__file__).parents[2]/'prompts/uhkegryo-interpreter-v4.md')))
    captured=[]
    async def generate(settings,messages,schema):
        captured.extend(messages)
        return json.dumps({'route':RecallQuery(mode='none').model_dump(mode='json'),
            'interpretation':chat().model_dump(mode='json')},ensure_ascii=False)
    adapter._generate=generate
    result=asyncio.run(adapter.route_and_interpret('다른 건?',job_id='scope',session_id='synthetic',
        attempt=1,max_attempts=1,session_context={'recent':[]}))
    assert result.interpretation.interpretation_state == 'drawing_chat'
    assert 'CHARACTER-FOCUSED SERVICE SCOPE' in captured[0]['content']
    assert 'Do not treat older assistant suggestions about props or backgrounds as permission' in captured[0]['content']


@pytest.mark.parametrize('request_text,term_id,evidence', [
    ('앉아 있는 캐릭터 레퍼런스를 찾아줘', 'pose_sitting', '앉아 있는'),
    ('서 있는 캐릭터 레퍼런스를 찾아줘', 'pose_standing', '서 있는'),
])
def test_explicit_character_posture_survives_scope_without_a_fixed_sitting_fallback(request_text,term_id,evidence):
    from backend.services.catalog_repository import load_catalog
    snapshot=load_catalog(Path(__file__).parents[2]/'docs/domains/illustration-reference/term-cards')
    interpreted=InterpretationOutput(interpretation_state='select_terms',answer_text='캐릭터의 몸 중심과 다리 방향을 살펴보세요.',
        selections=[{'role':'pose','term_id':term_id,'evidence':[evidence],'confidence':1}])
    resolution=resolve(interpreted,snapshot,request_text=request_text)
    assert resolution.status=='proceed'
    assert [term.selection.term_id for term in resolution.terms]==[term_id]
