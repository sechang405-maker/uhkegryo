import pytest
from pydantic import ValidationError
from backend.schemas.models import InterpretationOutput, AgentResult


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
