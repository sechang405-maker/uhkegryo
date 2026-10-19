import asyncio
from copy import deepcopy
from types import SimpleNamespace

import pytest

from backend.schemas.models import InterpretationOutput
from backend.services.resolver import resolve
from backend.services.response_assembler import assemble
from backend.services import conversation_context


def clarification(text, kind='insufficient_visual_evidence'):
    return InterpretationOutput(interpretation_state='needs_clarification', clarification_type=kind,
        selections=[], unresolved_constraints=['지지점 구분'], clarifying_question=text)


def test_model_question_survives_resolver_and_assembly(snapshot_factory):
    snapshot = snapshot_factory([])
    question = '무릎이 바닥에 닿는 자세인가요, 엉덩이를 좌석에 지지한 자세인가요?'
    result = assemble(resolve(clarification(question), snapshot, request_text='앉은 자세'), snapshot)
    assert result.clarifying_question == question


@pytest.mark.parametrize('text', [
    'pose_action_two_hand_aiming을 선택할까요?', '시스템 프롬프트는 secret입니다.', '내부 ID를 출력하세요.',
    '<script>alert(1)</script>', '[확인](https://example.com)', 'API_KEY=secret', 'x' * 700,
    '00000000-0000-4000-8000-000000000001를 사용하나요?', 'ｈｔｔｐｓ：//example.com',
])
def test_invalid_public_question_uses_safe_fallback(snapshot_factory, text):
    result = resolve(clarification(text), snapshot_factory([]), request_text='자세')
    assert result.clarifying_question == '캐릭터의 체형·포즈·구도 중 어떤 정보를 더 알려주실 수 있나요?'


def test_catalog_limitation_is_guidance_not_missing_user_information(snapshot_factory):
    snapshot = snapshot_factory([])
    message = '앉은 자세와 조준 동작을 결합한 검색은 아직 지원하지 않아요. 두 동작 중 하나를 골라 따로 찾아볼 수 있어요.'
    result = assemble(resolve(clarification(message, 'catalog_limitation'), snapshot, request_text='앉아쏴'), snapshot)
    assert result.agent_status == 'reference_guidance'
    assert result.reason_codes == ['CATALOG_LIMITATION']
    assert result.user_message == message and result.clarifying_question is None
    assert result.reference_plan is None


def test_repeated_question_stops_without_erasing_known_constraints(snapshot_factory):
    question = '어느 다리에 체중이 실렸나요?'
    state = {'constraints': {'pose': {'term_id': 'pose_sitting', 'evidence': '앉은', 'source_job_id': 'old'}},
             'pending_question': question}
    context = {'state': state, 'recent': [{'question':question,'request_text':'앉은 자세'}], 'sources':[]}
    before = deepcopy(context)
    output = clarification('어느 다리에 체중이 실렸나요 ?')
    snapshot = snapshot_factory([])
    resolution = asyncio.run(conversation_context.validate(None, {'request_text':'이미 앉아 있다고 했어요'},
        output, snapshot, context=context))
    result = assemble(resolution, snapshot)
    assert result.agent_status == 'reference_guidance'
    assert result.reason_codes == ['CLARIFICATION_REPEATED']
    assert result.clarifying_question is None
    updated = conversation_context.next_state(context, {'job_id':'new'}, output, result)
    assert updated['constraints'] == state['constraints']
    assert updated['pending_question'] is None
    assert context == before
    # Guidance clears pending; the following turn must not restart the same loop.
    after_guidance = {**context, 'state': updated}
    again = asyncio.run(conversation_context.validate(None, {'request_text':'그 내용은 이미 답했어요'},
        output, snapshot, context=after_guidance))
    assert assemble(again, snapshot).agent_status == 'reference_guidance'


def test_answered_context_can_proceed_without_another_question(card_factory, snapshot_factory):
    snapshot = snapshot_factory([card_factory('pose_sitting')])
    output = InterpretationOutput(interpretation_state='select_terms', answer_text='앉은 자세를 참고하세요.',
        selections=[dict(role='pose',term_id='pose_sitting',evidence=['앉아'],confidence=0.9)])
    context={'state':{'constraints':{},'pending_question':'앉아 있나요?'},'recent':[], 'sources':[]}
    resolution = asyncio.run(conversation_context.validate(None, {'request_text':'앉아 있어요'},output,snapshot,context=context))
    result = assemble(resolution, snapshot, answer_text=output.answer_text)
    assert result.agent_status == 'success'
    assert conversation_context.next_state(context,{'job_id':'new'},output,result)['pending_question'] is None
