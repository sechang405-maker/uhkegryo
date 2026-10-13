import pytest
import json
import asyncio
from pydantic import ValidationError
from backend.schemas.models import InterpretationOutput, AgentResult
from backend.services.llm import LLMInvalidStructuredOutput, _validate_output
from backend.services.conversation_context import validate


@pytest.mark.parametrize("model,payload", [
    (InterpretationOutput, {"interpretation_state": "needs_clarification", "unresolved_constraints": ["자세"],
                           "clarifying_question": "어떤 자세인가요?", "clarification_type": "insufficient_visual_evidence"}),
    (AgentResult, {"agent_status": "needs_clarification", "reason_codes": ["INSUFFICIENT_VISUAL_EVIDENCE"],
                   "clarifying_question": "어떤 자세인가요?"}),
])
def test_answer_contract_compatibility_and_bounds(model, payload):
    assert model(**payload).answer_text == ""
    assert model(**payload, answer_text="가" * 4000).answer_text == "가" * 4000
    for invalid in ["가" * 4001, None, 42, []]:
        with pytest.raises(ValidationError):
            model(**payload, answer_text=invalid)


@pytest.mark.parametrize("answer_text", ["", "  \n  "])
def test_select_terms_without_readable_answer_is_invalid_model_output(answer_text):
    payload = {
        "interpretation_state": "select_terms",
        "selections": [{"role": "pose", "term_id": "pose_shift", "evidence": ["한쪽 다리"], "confidence": 0.9}],
        "unresolved_constraints": [],
        "clarifying_question": None,
        "clarification_type": None,
        "answer_text": answer_text,
    }
    with pytest.raises(LLMInvalidStructuredOutput):
        _validate_output(json.dumps(payload, ensure_ascii=False))


@pytest.mark.parametrize("term_id,valid", [("pose_standing", True), ("pose_unknown", False)])
def test_context_update_checks_catalog_without_losing_answer(snapshot_factory, card_factory, term_id, valid):
    snapshot = snapshot_factory([card_factory("pose_standing")])
    output = InterpretationOutput(
        interpretation_state="select_terms",
        selections=[{"role": "pose", "term_id": "pose_standing", "evidence": ["standing"], "confidence": 0.9}],
        context_updates=[{"role": "pose", "term_id": term_id, "evidence": "standing"}],
        answer_text="서 있는 자세를 참고해 보세요.",
    )
    if valid:
        result = asyncio.run(validate(None, {"request_text": "standing"}, output, snapshot))
        assert result.status == "proceed"
        assert output.answer_text == "서 있는 자세를 참고해 보세요."
    else:
        with pytest.raises(LLMInvalidStructuredOutput) as exc:
            asyncio.run(validate(None, {"request_text": "standing"}, output, snapshot))
        assert exc.value.feedback[0]["code"] == "context_card_invalid"
