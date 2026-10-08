"""api-contract AC-07 · term-card-catalog 피드백 매핑 기반 응답 조립 테스트."""

from backend.schemas.enums import (
    AgentStatus,
    ClarificationType,
    InterpretationState,
    PinStatus,
    ReasonCode,
    Role,
)
from backend.schemas.models import InterpretationOutput, InterpretationSelection, PinResult
from backend.services.response_assembler import RoleSearchOutcome, assemble
from backend.services.resolver import resolve

BASE = "https://www.pinterest.com/search/pins/"


def test_clarification_does_not_expose_model_answer(snapshot_factory):
    from backend.services.resolver import ResolutionResult, STATUS_CLARIFY
    result = assemble(ResolutionResult(status=STATUS_CLARIFY,
        reason_codes=[ReasonCode.INSUFFICIENT_VISUAL_EVIDENCE], clarifying_question="어떤 자세인가요?"),
        snapshot_factory([]), answer_text="검증되지 않은 설명")
    assert result.answer_text == ""


def _interpretation(selections):
    return InterpretationOutput(
        interpretation_state=InterpretationState.SELECT_TERMS,
        selections=selections,
        unresolved_constraints=[],
        clarifying_question=None,
        clarification_type=None,
    )


def _sel(role, term_id, confidence=0.9):
    return InterpretationSelection(
        role=role, term_id=term_id, evidence=["단서"], confidence=confidence
    )


def _pin(url="https://pin.it/1", status="available"):
    return PinResult(pin_id=url.rsplit("/", 1)[-1], pin_url=url, thumbnail_url=url if status == "available" else None, status=status)


def _resolve(selections, snapshot):
    return resolve(_interpretation(selections), snapshot, request_text="단서")


def test_feedback_mapping_takes_priority(snapshot_factory, card_factory):
    """EVAL-28: 활성 팀 카드 피드백을 근거로 조립. LLM이 문구를 만들지 않는다."""
    cards = [card_factory("body_hourglass", role="body")]
    feedback = {
        "body_hourglass": {
            "plain_meaning_ko": "어깨와 골반이 비슷하고 허리가 들어간 체형",
            "selection_reason_template_ko": "입력의 잘록한 허리 표현에서 해석",
            "reference_checkpoints_ko": ["어깨 폭", "허리 라인", "골반 폭"],
        }
    }
    snapshot = snapshot_factory(cards, feedback=feedback)
    result = assemble(_resolve([_sel("body", "body_hourglass")], snapshot), snapshot)

    assert result.agent_status == AgentStatus.SUCCESS
    assert result.reason_codes == []
    term = result.reference_plan.terms[0]
    assert term.term_id == "body_hourglass"
    assert term.plain_meaning_ko == "어깨와 골반이 비슷하고 허리가 들어간 체형"
    assert term.selection_reason == "입력의 잘록한 허리 표현에서 해석"
    assert term.reference_checkpoints == ["어깨 폭", "허리 라인", "골반 폭"]
    assert term.search_url.startswith(BASE)


def test_fallback_mapping_when_no_feedback(snapshot_factory, card_factory):
    cards = [card_factory("body_slim", role="body", source_answer_draft="날씬한 체형 초안")]
    snapshot = snapshot_factory(cards, feedback={})
    result = assemble(_resolve([_sel("body", "body_slim")], snapshot), snapshot)
    term = result.reference_plan.terms[0]
    assert term.plain_meaning_ko == "날씬한 체형 초안"
    assert term.selection_reason is None
    assert term.reference_checkpoints == ["라벨 관찰 지점"]


def test_plan_role_order_and_unresolved(snapshot_factory, card_factory):
    cards = [card_factory("body_slim", role="body")]
    snapshot = snapshot_factory(cards)
    result = assemble(_resolve([_sel("body", "body_slim")], snapshot), snapshot)
    assert [t.role for t in result.reference_plan.terms] == [Role.BODY]
    assert result.reference_plan.unresolved_roles == [
        Role.POSE,
        Role.VIEW,
        Role.PERSPECTIVE,
        Role.LAYOUT,
    ]


def test_partial_result_when_zero_pins(snapshot_factory, card_factory):
    """EVAL-24: 정상 검색 0건 — 재시도하지 않고 PIN_RESULTS_EMPTY."""
    cards = [card_factory("pose_weight_shift", role="pose")]
    snapshot = snapshot_factory(cards)
    resolution = _resolve([_sel("pose", "pose_weight_shift")], snapshot)
    outcome = RoleSearchOutcome(role=Role.POSE, pins=[], code=ReasonCode.PIN_RESULTS_EMPTY)
    result = assemble(resolution, snapshot, search_outcomes={Role.POSE: outcome})

    assert result.agent_status == AgentStatus.PARTIAL_RESULT
    assert result.reason_codes == [ReasonCode.PIN_RESULTS_EMPTY]
    term = result.reference_plan.terms[0]
    assert term.pins == []
    assert term.reason_codes == [ReasonCode.PIN_RESULTS_EMPTY]


def test_partial_result_when_search_unavailable(snapshot_factory, card_factory):
    """EVAL-26: provider timeout 재시도 소진 — PIN_SEARCH_UNAVAILABLE."""
    cards = [card_factory("view_three_quarter", role="view")]
    snapshot = snapshot_factory(cards)
    resolution = _resolve([_sel("view", "view_three_quarter")], snapshot)
    outcome = RoleSearchOutcome(role=Role.VIEW, code=ReasonCode.PIN_SEARCH_UNAVAILABLE)
    result = assemble(resolution, snapshot, search_outcomes={Role.VIEW: outcome})

    assert result.agent_status == AgentStatus.PARTIAL_RESULT
    assert result.reason_codes == [ReasonCode.PIN_SEARCH_UNAVAILABLE]
    assert result.reference_plan.terms[0].reason_codes == [ReasonCode.PIN_SEARCH_UNAVAILABLE]


def test_pins_preserved_with_original_order(snapshot_factory, card_factory):
    """EVAL-23: 역할별 최대 8개, 원본 순서 보존, 원본 링크·응답 전용 썸네일."""
    cards = [card_factory("body_slim", role="body")]
    snapshot = snapshot_factory(cards)
    pins = [_pin(f"https://pin.it/{i}") for i in range(3)]
    resolution = _resolve([_sel("body", "body_slim")], snapshot)
    result = assemble(
        resolution, snapshot, search_outcomes={Role.BODY: RoleSearchOutcome(role=Role.BODY, pins=pins)}
    )

    assert result.agent_status == AgentStatus.SUCCESS
    term = result.reference_plan.terms[0]
    assert [p.pin_url for p in term.pins] == ["https://pin.it/0", "https://pin.it/1", "https://pin.it/2"]
    assert term.pins[0].thumbnail_url is not None
    assert term.pins[0].status == PinStatus.AVAILABLE


def test_aggregated_codes_unique_in_role_order(snapshot_factory, card_factory):
    cards = [
        card_factory("body_slim", role="body"),
        card_factory("pose_weight_shift", role="pose"),
    ]
    snapshot = snapshot_factory(cards)
    resolution = _resolve(
        [_sel("body", "body_slim"), _sel("pose", "pose_weight_shift")], snapshot
    )
    outcomes = {
        Role.BODY: RoleSearchOutcome(role=Role.BODY, code=ReasonCode.PIN_RESULTS_EMPTY),
        Role.POSE: RoleSearchOutcome(role=Role.POSE, code=ReasonCode.PIN_RESULTS_EMPTY),
    }
    result = assemble(resolution, snapshot, search_outcomes=outcomes)

    assert result.agent_status == AgentStatus.PARTIAL_RESULT
    assert result.reason_codes == [ReasonCode.PIN_RESULTS_EMPTY]  # 중복 제거


def test_clarify_assembles_state_without_plan(snapshot_factory, card_factory):
    cards = [card_factory("pose_contrapposto", role="pose")]
    snapshot = snapshot_factory(cards)
    interp = InterpretationOutput(
        interpretation_state=InterpretationState.NEEDS_CLARIFICATION,
        selections=[],
        unresolved_constraints=["단서 부족"],
        clarifying_question="어떤 포즈 축인가요?",
        clarification_type=ClarificationType.INSUFFICIENT_VISUAL_EVIDENCE,
    )
    resolution = resolve(interp, snapshot, request_text="단서 부족")
    result = assemble(resolution, snapshot)

    assert result.agent_status == AgentStatus.NEEDS_CLARIFICATION
    assert result.reason_codes == [ReasonCode.INSUFFICIENT_VISUAL_EVIDENCE]
    assert result.clarifying_question == (
        "캐릭터의 체형·포즈·시점 중 어떤 정보를 더 알려주실 수 있나요?"
    )
    assert result.reference_plan is None
