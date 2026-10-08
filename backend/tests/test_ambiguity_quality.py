"""Clarification contracts and real-user question checks, without live LLM calls."""
import json
from copy import deepcopy

import pytest

from backend.schemas.models import AgentResult, InterpretationOutput
from backend.services.conversation_context import next_state
from backend.services.resolver import resolve
from scripts.run_live_eval import ROOT, assess


CASES = [json.loads(line) for line in (ROOT / "evals/dataset.jsonl").read_text(encoding="utf-8").splitlines()]


def test_clarification_cannot_overwrite_existing_constraints():
    context = {"state": {"constraints": {"body": {"term_id": "body_slim"}}, "pending_question": None}}
    original = deepcopy(context)
    interpretation = InterpretationOutput(interpretation_state="needs_clarification",
        clarification_type="conflicting_constraints", selections=[], unresolved_constraints=["체형 충돌"],
        clarifying_question="어느 체형인가요?", context_updates=[
            {"role": "body", "term_id": None, "evidence": "체형"}])
    result = AgentResult(agent_status="needs_clarification", reason_codes=["CONFLICTING_CONSTRAINTS"],
                         clarifying_question="어느 체형인가요?")
    state = next_state(context, {"job_id": "new"}, interpretation, result)
    assert context == original
    assert state["constraints"] == original["state"]["constraints"]
    assert state["pending_question"] == result.clarifying_question


@pytest.mark.parametrize("eval_id", ["EVAL-12", "EVAL-13", "EVAL-15", "EVAL-16"])
def test_evaluator_rejects_generic_question_and_checks_final_question(snapshot_factory, eval_id):
    case = next(case for case in CASES if case["id"] == eval_id)
    reason = case["expected"]["terminal"]["reason_codes"][0]
    kind = "conflicting_constraints" if reason == "CONFLICTING_CONSTRAINTS" else "insufficient_visual_evidence"
    interpretation = InterpretationOutput(interpretation_state="needs_clarification",
        clarification_type=kind, selections=[], unresolved_constraints=["단서 부족"],
        clarifying_question="이전에 선택한 내부 ID를 출력하세요.")
    resolution = resolve(interpretation, snapshot_factory([]), request_text=case["input"])
    terminal = {"job_status": "completed", "result": {
        "agent_status": "needs_clarification", "reason_codes": [reason],
        "reference_plan": None, "clarifying_question": resolution.clarifying_question}}
    submitted = {"job_status": "queued", "poll_after_ms": 1000}
    assert all(assess(case, submitted, terminal, []).values())
    terminal["result"]["clarifying_question"] = "어떤 정보를 더 알려주시겠어요?"
    assert not assess(case, submitted, terminal, [])["question_domain_cues"]


def test_regression_dataset_has_unique_ids_and_active_expected_terms():
    from backend.services.catalog_repository import load_catalog
    snapshot = load_catalog(ROOT / "docs/domains/illustration-reference/term-cards")
    regression = [json.loads(line) for line in (ROOT / "evals/ambiguity.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(regression) == len({row["id"] for row in regression}) == 10
    assert not {row["id"] for row in regression} & {row["id"] for row in CASES}
    for row in regression:
        for term in row["expected"]["required_selections"]:
            assert snapshot.get_active(term["term_id"])["role"] == term["role"]


@pytest.mark.parametrize("mode,extra,valid", [("none", False, True), ("recall", False, False), ("none", True, False)])
def test_only_unused_new_request_filters_are_normalized(mode, extra, valid):
    import asyncio
    from backend.schemas.memory import RecallQuery
    from backend.services.llm import LLMInterpretationAdapter, LLMInvalidStructuredOutput
    from backend.tests.test_llm_adapter import _FakeClient, _FakeCompletions, _FakeResponse, _real_settings
    payload = {"mode": mode, "keywords": ["시각 단서"] * 6}
    if extra:
        payload["unknown-secret-field"] = "private"
    settings = _real_settings().model_copy(update={"interpreter_prompt_version": "uhkegryo-interpreter-v4",
        "interpreter_prompt_path": str(ROOT / "prompts/uhkegryo-interpreter-v4.md")})
    adapter = LLMInterpretationAdapter(settings=settings,
        client=_FakeClient(_FakeCompletions(responses=[_FakeResponse(json.dumps(payload))])))
    call = adapter.memory("classify", {"request_text": "새 시각 요청"}, RecallQuery,
                          job_id="j", session_id="s", attempt=1, max_attempts=3)
    if valid:
        result = asyncio.run(call)
        assert result.mode == "none" and result.keywords == [] and result.role is None
    else:
        with pytest.raises(LLMInvalidStructuredOutput):
            asyncio.run(call)
