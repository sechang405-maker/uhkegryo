"""api-contract.md AC 기반 스키마 테스트 (backend/schemas)."""

import pytest
from pydantic import ValidationError

from backend.schemas import (
    AgentRequest,
    AgentResult,
    AgentStatus,
    ClarificationType,
    Failure,
    FailureCode,
    InterpretationOutput,
    InterpretationSelection,
    InterpretationState,
    JobEnvelope,
    JobStatus,
    PinResult,
    PinStatus,
    ReferencePlan,
    ReasonCode,
    Role,
    SubmissionResponse,
    TermResult,
)
from backend.schemas.models import MAX_PINS_PER_ROLE, PROGRESS_POLL_AFTER_MS


# ---------- enums ----------


@pytest.mark.parametrize(
    "enum_cls, expected",
    [
        (JobStatus, ["queued", "running", "validating", "searching", "rendering", "completed", "failed"]),
        (AgentStatus, ["success", "needs_clarification", "out_of_scope", "unsafe_input", "partial_result", "memory_answer"]),
        (PinStatus, ["available", "deleted"]),
        (
            ReasonCode,
            [
                "ABSTRACT_INTENT_ONLY",
                "INSUFFICIENT_VISUAL_EVIDENCE",
                "CONFLICTING_CONSTRAINTS",
                "DIRECT_SEARCH_DISABLED",
                "PIN_RESULTS_EMPTY",
                "PIN_SEARCH_UNAVAILABLE",
                "OUT_OF_SCOPE_REQUEST",
                "UNSAFE_INPUT",
            ],
        ),
        (
            FailureCode,
            [
                "LLM_TIMEOUT",
                "LLM_RATE_LIMITED",
                "LLM_UPSTREAM_UNAVAILABLE",
                "LLM_INVALID_STRUCTURED_OUTPUT",
                "SEARCH_TIMEOUT",
                "SEARCH_RATE_LIMITED",
                "SEARCH_UPSTREAM_UNAVAILABLE",
                "JOB_INSTANCE_INTERRUPTED",
                "CONFIGURATION_ERROR",
                "DATABASE_MIGRATION_ERROR",
                "DATABASE_UNAVAILABLE",
                "CATALOG_INVALID_AT_STARTUP",
                "INTERNAL_CODE_ERROR",
            ],
        ),
        (InterpretationState, ["select_terms", "needs_clarification"]),
        (
            ClarificationType,
            ["abstract_intent", "insufficient_visual_evidence", "conflicting_constraints"],
        ),
    ],
)
def test_enum_values(enum_cls, expected):
    assert [e.value for e in enum_cls] == expected


def test_enum_is_str_subclass():
    assert JobStatus.QUEUED == "queued"
    assert AgentStatus.SUCCESS == "success"


# ---------- AgentRequest (AC-01, api-contract §What) ----------


def test_agent_request_valid():
    req = AgentRequest(request_text="마른 체형 캐릭터")
    assert req.request_text == "마른 체형 캐릭터"


def test_agent_request_rejects_whitespace_only():
    with pytest.raises(ValidationError):
        AgentRequest(request_text="   ")


@pytest.mark.parametrize("text", ["", "a" * 501])
def test_agent_request_rejects_length(text):
    with pytest.raises(ValidationError):
        AgentRequest(request_text=text)


def test_agent_request_rejects_extra_fields():
    with pytest.raises(ValidationError):
        AgentRequest(request_text="질문", role="body", term_id="pose_contrapposto")


def test_agent_request_accepts_session_id_with_conversation_route():
    request = AgentRequest(request_text="질문", session_id="00000000-0000-0000-0000-000000000001")
    assert str(request.session_id) == "00000000-0000-0000-0000-000000000001"


# ---------- SubmissionResponse ----------


def test_submission_response_defaults():
    resp = SubmissionResponse(job_id="j1")
    assert resp.job_status == "queued"
    assert resp.poll_after_ms == PROGRESS_POLL_AFTER_MS


def test_submission_response_rejects_non_queued():
    with pytest.raises(ValidationError):
        SubmissionResponse(job_id="j1", job_status="completed")


# ---------- PinResult / TermResult (AC-07, §What) ----------


def _term_result(**overrides):
    base = {
        "role": "pose",
        "term_id": "pose_contrapposto",
        "label_ko": "콘트라포스토",
        "label_en": "contrapposto",
        "plain_meaning_ko": "한 다리에 체중이 실리고 골반과 어깨가 반대 방향으로 기울어진 자세",
        "reference_checkpoints": ["한쪽 다리에 체중", "어깨-골반 반대 기울기"],
        "search_url": "https://pinterest.com/search/pins/?q=contrapposto+pose",
        "pins": [
            {"pin_id": "1", "pin_url": "https://pin.it/1", "thumbnail_url": "https://pin.it/t1", "status": "available"}
        ],
        "reason_codes": [],
    }
    base.update(overrides)
    return TermResult(**base)


def test_term_result_valid():
    term = _term_result()
    assert term.pins[0].status == PinStatus.AVAILABLE


def test_deleted_pin_has_no_thumbnail_url():
    term = _term_result(pins=[{"pin_id": "1", "pin_url": "https://pin.it/1", "status": "deleted"}])
    assert term.pins[0].thumbnail_url is None
    with pytest.raises(ValidationError):
        _term_result(
            pins=[
                {
                    "pin_id": "1",
                    "pin_url": "https://pin.it/1",
                    "thumbnail_url": "https://pin.it/t1",
                    "status": "deleted",
                }
            ]
        )


def test_term_result_rejects_pin_reason_codes():
    with pytest.raises(ValidationError):
        _term_result(reason_codes=["OUT_OF_SCOPE_REQUEST"])


def test_term_result_allows_pin_empty_codes():
    assert _term_result(reason_codes=["PIN_RESULTS_EMPTY"]).reason_codes == [ReasonCode.PIN_RESULTS_EMPTY]
    assert _term_result(reason_codes=["PIN_SEARCH_UNAVAILABLE"]).reason_codes == [ReasonCode.PIN_SEARCH_UNAVAILABLE]


def test_term_result_rejects_multiple_reason_codes():
    with pytest.raises(ValidationError):
        _term_result(reason_codes=["PIN_RESULTS_EMPTY", "PIN_SEARCH_UNAVAILABLE"])


def test_term_result_rejects_too_many_pins():
    pins = [{"pin_url": f"https://pin.it/{i}", "status": "available"} for i in range(MAX_PINS_PER_ROLE + 1)]
    with pytest.raises(ValidationError):
        _term_result(pins=pins)


# ---------- ReferencePlan (§What: 역할당 최대 1개·순서) ----------


def _reference_plan(**overrides):
    base = {
        "terms": [
            _term_result(role="body", term_id="body_slim"),
            _term_result(role="pose", term_id="pose_contrapposto"),
        ],
        "unresolved_roles": ["view"],
    }
    base.update(overrides)
    return ReferencePlan(**base)


def test_reference_plan_valid():
    plan = _reference_plan()
    assert [t.role for t in plan.terms] == [Role.BODY, Role.POSE]


def test_reference_plan_rejects_duplicate_role():
    with pytest.raises(ValidationError):
        _reference_plan(
            terms=[
                _term_result(role="pose", term_id="pose_contrapposto"),
                _term_result(role="pose", term_id="pose_s_curve"),
            ]
        )


def test_reference_plan_rejects_wrong_role_order():
    with pytest.raises(ValidationError):
        _reference_plan(
            terms=[
                _term_result(role="pose", term_id="pose_contrapposto"),
                _term_result(role="body", term_id="body_slim"),
            ]
        )


def test_reference_plan_rejects_role_overlap():
    with pytest.raises(ValidationError):
        _reference_plan(
            terms=[_term_result(role="pose", term_id="pose_contrapposto")],
            unresolved_roles=["pose"],
        )


# ---------- AgentResult (AC-03·AC-07, §What 상태별 규칙) ----------


def _agent_result(**overrides):
    base = {
        "agent_status": "success",
        "reason_codes": [],
        "reference_plan": _reference_plan(),
        "clarifying_question": None,
        "user_message": "참조 자료를 찾았습니다.",
    }
    base.update(overrides)
    return AgentResult(**base)


def test_agent_result_success_requires_plan():
    with pytest.raises(ValidationError):
        _agent_result(reference_plan=None)


def test_agent_result_success_rejects_reason_codes():
    with pytest.raises(ValidationError):
        _agent_result(reason_codes=["PIN_RESULTS_EMPTY"])


def test_agent_result_partial_result_allowed_codes():
    result = _agent_result(agent_status="partial_result", reason_codes=["PIN_RESULTS_EMPTY"])
    assert result.agent_status == AgentStatus.PARTIAL_RESULT
    with pytest.raises(ValidationError):
        _agent_result(agent_status="partial_result", reason_codes=["OUT_OF_SCOPE_REQUEST"])


def test_agent_result_needs_clarification_rules():
    result = _agent_result(
        agent_status="needs_clarification",
        reason_codes=["ABSTRACT_INTENT_ONLY"],
        clarifying_question="어떤 체형인가요?",
        reference_plan=None,
    )
    assert result.clarifying_question
    with pytest.raises(ValidationError):
        _agent_result(
            agent_status="needs_clarification",
            reason_codes=[],
            clarifying_question="어떤 체형인가요?",
            reference_plan=None,
        )


def test_agent_result_out_of_scope_requires_single_code():
    result = _agent_result(
        agent_status="out_of_scope", reason_codes=["OUT_OF_SCOPE_REQUEST"], reference_plan=None
    )
    assert result.reason_codes == [ReasonCode.OUT_OF_SCOPE_REQUEST]
    with pytest.raises(ValidationError):
        _agent_result(agent_status="out_of_scope", reference_plan=None)


def test_agent_result_unsafe_input_requires_single_code():
    result = _agent_result(
        agent_status="unsafe_input", reason_codes=["UNSAFE_INPUT"], reference_plan=None
    )
    assert result.reason_codes == [ReasonCode.UNSAFE_INPUT]
    with pytest.raises(ValidationError):
        _agent_result(agent_status="unsafe_input", reference_plan=None, reason_codes=["UNSAFE_INPUT", "PIN_RESULTS_EMPTY"])


def test_agent_result_rejects_duplicate_reason_codes():
    with pytest.raises(ValidationError):
        _agent_result(
            agent_status="needs_clarification",
            reason_codes=["ABSTRACT_INTENT_ONLY", "ABSTRACT_INTENT_ONLY"],
            clarifying_question="질문",
            reference_plan=None,
        )


# ---------- Failure / JobEnvelope (AC-04·AC-06, §What 상태별) ----------


def _failure(**overrides):
    base = {"failure_code": "LLM_TIMEOUT", "user_message": "처리하지 못했습니다.", "retryable": False}
    base.update(overrides)
    return Failure(**base)


def test_failure_retryable_false():
    failure = _failure()
    assert failure.retryable is False


def test_failure_rejects_retryable_true():
    with pytest.raises(ValidationError):
        _failure(retryable=True)


def _job_envelope(**overrides):
    base = {
        "job_id": "j1",
        "session_id": "s1",
        "job_status": "queued",
        "attempt": 1,
        "max_attempts": 3,
        "poll_after_ms": PROGRESS_POLL_AFTER_MS,
        "result": None,
        "failure": None,
    }
    base.update(overrides)
    return JobEnvelope(**base)


def test_job_envelope_progress_requires_poll_after_ms():
    job = _job_envelope()
    assert job.poll_after_ms == PROGRESS_POLL_AFTER_MS
    with pytest.raises(ValidationError):
        _job_envelope(poll_after_ms=None)


def test_job_envelope_progress_rejects_result_or_failure():
    with pytest.raises(ValidationError):
        _job_envelope(result=_agent_result())
    with pytest.raises(ValidationError):
        _job_envelope(failure=_failure())


def test_job_envelope_completed_requires_result():
    job = _job_envelope(
        job_status="completed",
        poll_after_ms=None,
        result=_agent_result(),
    )
    assert job.job_status == JobStatus.COMPLETED
    with pytest.raises(ValidationError):
        _job_envelope(job_status="completed", poll_after_ms=None)


def test_job_envelope_failed_requires_failure():
    job = _job_envelope(job_status="failed", poll_after_ms=None, failure=_failure())
    assert job.failure.failure_code == FailureCode.LLM_TIMEOUT
    with pytest.raises(ValidationError):
        _job_envelope(job_status="failed", poll_after_ms=None)


def test_job_envelope_attempt_bounds():
    with pytest.raises(ValidationError):
        _job_envelope(attempt=0)
    with pytest.raises(ValidationError):
        _job_envelope(max_attempts=4)
    with pytest.raises(ValidationError):
        _job_envelope(attempt=4, max_attempts=3)


# ---------- InterpretationOutput (§How: LLM 어댑터 전용) ----------


def _interpretation_output(**overrides):
    base = {
        "interpretation_state": "select_terms",
        "selections": [
            InterpretationSelection(role="body", term_id="body_slim", evidence=["마른 체형"], confidence=0.9)
        ],
        "unresolved_constraints": [],
        "clarifying_question": None,
        "clarification_type": None,
    }
    base.update(overrides)
    return InterpretationOutput(**base)


def test_interpretation_output_select_terms_valid():
    out = _interpretation_output(
        selections=[
            InterpretationSelection(role="body", term_id="body_slim", evidence=["마른 체형"], confidence=0.9),
            InterpretationSelection(role="pose", term_id="pose_contrapposto", evidence=["한쪽 다리에 힘"], confidence=0.8),
        ]
    )
    assert out.interpretation_state == InterpretationState.SELECT_TERMS
    assert [s.role for s in out.selections] == [Role.BODY, Role.POSE]


def test_interpretation_output_needs_clarification_valid():
    out = _interpretation_output(
        interpretation_state="needs_clarification",
        selections=[],
        unresolved_constraints=["체형 비율을 확정할 실제 신체 단서가 없음"],
        clarifying_question="의상을 제외한 실제 체형 비율을 찾으시나요?",
        clarification_type="insufficient_visual_evidence",
    )
    assert out.interpretation_state == InterpretationState.NEEDS_CLARIFICATION
    assert out.clarification_type == ClarificationType.INSUFFICIENT_VISUAL_EVIDENCE


def test_interpretation_output_rejects_final_state_fields():
    with pytest.raises(ValidationError):
        _interpretation_output(
            agent_status="success",
            reference_plan={},
        )


def test_interpretation_output_rejects_invalid_state_value():
    with pytest.raises(ValidationError):
        InterpretationOutput(
            interpretation_state="proposed",
            selections=[],
            unresolved_constraints=[],
            clarifying_question=None,
        )


@pytest.mark.parametrize(
    "overrides",
    [
        {"selections": []},
        {
            "selections": [
                InterpretationSelection(role="pose", term_id="pose_contrapposto", evidence=["a"], confidence=0.8),
                InterpretationSelection(role="pose", term_id="pose_s_curve", evidence=["b"], confidence=0.7),
            ]
        },
        {
            "selections": [
                InterpretationSelection(role="pose", term_id="pose_contrapposto", evidence=["a"], confidence=0.8),
                InterpretationSelection(role="body", term_id="body_slim", evidence=["b"], confidence=0.9),
            ]
        },
        {"unresolved_constraints": ["구도 미언급"]},
        {"clarifying_question": "어떤 체형인가요?"},
        {"clarification_type": "conflicting_constraints"},
    ],
)
def test_interpretation_output_select_terms_invalid(overrides):
    with pytest.raises(ValidationError):
        _interpretation_output(**overrides)


@pytest.mark.parametrize(
    "overrides",
    [
        {
            "interpretation_state": "needs_clarification",
            "selections": [
                InterpretationSelection(role="body", term_id="body_slim", evidence=["마른 체형"], confidence=0.9)
            ],
            "unresolved_constraints": ["단서 부족"],
            "clarifying_question": "질문?",
            "clarification_type": "insufficient_visual_evidence",
        },
        {
            "interpretation_state": "needs_clarification",
            "selections": [],
            "unresolved_constraints": [],
            "clarifying_question": "질문?",
            "clarification_type": "insufficient_visual_evidence",
        },
        {
            "interpretation_state": "needs_clarification",
            "selections": [],
            "unresolved_constraints": ["단서 부족"],
            "clarifying_question": None,
            "clarification_type": "insufficient_visual_evidence",
        },
        {
            "interpretation_state": "needs_clarification",
            "selections": [],
            "unresolved_constraints": ["단서 부족"],
            "clarifying_question": "   ",
            "clarification_type": "insufficient_visual_evidence",
        },
        {
            "interpretation_state": "needs_clarification",
            "selections": [],
            "unresolved_constraints": ["단서 부족"],
            "clarifying_question": "질문?",
            "clarification_type": None,
        },
    ],
)
def test_interpretation_output_needs_clarification_invalid(overrides):
    with pytest.raises(ValidationError):
        _interpretation_output(**overrides)


@pytest.mark.parametrize(
    "evidence",
    [
        [],
        [""],
        ["  "],
        ["유효한 단서", ""],
    ],
)
def test_interpretation_selection_rejects_empty_evidence(evidence):
    with pytest.raises(ValidationError):
        InterpretationSelection(role="body", term_id="body_slim", evidence=evidence, confidence=0.9)
@pytest.mark.parametrize("confidence", [-0.1, 1.1])
def test_interpretation_selection_rejects_confidence_out_of_range(confidence):
    with pytest.raises(ValidationError):
        InterpretationSelection(
            role="body", term_id="body_slim", evidence=["마른 체형"], confidence=confidence
        )


@pytest.mark.parametrize("confidence", [0.0, 1.0, 0.5])
def test_interpretation_selection_accepts_confidence_boundaries(confidence):
    selection = InterpretationSelection(
        role="body", term_id="body_slim", evidence=["마른 체형"], confidence=confidence
    )
    assert selection.confidence == confidence


@pytest.mark.parametrize(
    "unresolved_constraints",
    [
        [""],
        ["   "],
        ["유효한 단서", ""],
    ],
)
def test_interpretation_output_rejects_whitespace_unresolved_constraints(unresolved_constraints):
    with pytest.raises(ValidationError):
        _interpretation_output(
            interpretation_state="needs_clarification",
            selections=[],
            unresolved_constraints=unresolved_constraints,
            clarifying_question="질문?",
            clarification_type="abstract_intent",
        )
