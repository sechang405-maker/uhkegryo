"""실제 loader가 전달하는 v1 출력 계약의 회귀 검증."""
import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from backend.schemas.memory import ContextUpdate
from backend.schemas.models import InterpretationOutput, InterpretationSelection
from backend.services.llm import (
    LLMInterpretationAdapter,
    LLMInvalidStructuredOutput,
    _validate_output,
    load_interpreter_prompt,
)
from backend.shared.config import Settings
from backend.services import conversation_context
from backend.services.structured_output import load_skill

ROOT = Path(__file__).resolve().parents[2]
PROMPT = ROOT / "prompts" / "uhkegryo-interpreter-v1.md"


def test_loaded_system_contains_complete_selection_shape_and_valid_examples():
    system, user = load_interpreter_prompt(PROMPT)
    system += "\n" + load_skill(str(ROOT / "skills/structured-output/SKILL.md"))
    examples = [json.loads(line) for line in system.splitlines() if line.startswith('{"interpretation_state"')]
    assert len(examples) == 2
    selected, clarification = [InterpretationOutput.model_validate(item) for item in examples]
    top_fields = set(InterpretationOutput.model_fields)
    selection_fields = set(InterpretationSelection.model_fields)
    assert len(top_fields) == 7
    assert "Include every field" in system
    assert all(set(example) == top_fields for example in examples)
    assert set(examples[0]["selections"][0]) == selection_fields
    assert selected.selections[0].evidence
    assert clarification.selections == []
    assert clarification.clarification_type is not None
    assert "selections and unresolved_constraints are always arrays" in system
    assert "{{request_text}}" in user and "{{active_cards_json}}" in user


def test_semantic_prompt_does_not_define_output_shape():
    system, _ = load_interpreter_prompt(PROMPT)
    for shape_rule in ("JSON object", "always arrays", "For select_terms:",
                       "For needs_clarification:", "shape example:"):
        assert shape_rule not in system
    assert not any(line.startswith('{"interpretation_state"') for line in system.splitlines())


@pytest.mark.parametrize("source_job_id", [None, "00000000-0000-0000-0000-000000000001"])
def test_english_original_evidence_preserves_spelling(source_job_id):
    system, _ = load_interpreter_prompt(PROMPT)
    assert "preserve the original spelling and case, including English" in system
    system += "\n" + load_skill(str(ROOT / "skills/structured-output/SKILL.md"))
    example = next(json.loads(line) for line in system.splitlines()
                   if line.startswith('{"interpretation_state":"select_terms"'))
    example["selections"][0]["evidence"] = ["Low Angle 3/4"]
    example["selections"][0]["source_job_id"] = source_job_id
    result = _validate_output(json.dumps(example, ensure_ascii=False))
    assert result.selections[0].evidence == ["Low Angle 3/4"]


def test_loaded_system_separates_selection_and_context_update_sources():
    system, _ = load_interpreter_prompt(PROMPT)
    assert "selections[].evidence must preserve the original spelling and case, including English" in system
    assert "identified by a valid source_job_id" in system
    assert "context_updates[].evidence must preserve the original spelling and case, including English, from the current request only" in system
    assert "context_updates has no source_job_id field" in system
    assert "evidence and context_updates evidence" not in system


@pytest.mark.parametrize("update_evidence", ["High Angle", "Low Angle", "low angle"])
def test_context_update_uses_current_english_request_only(snapshot_factory, card_factory, update_evidence):
    source_id = "00000000-0000-0000-0000-000000000001"
    job = {"request_text": "Change the view to High Angle"}
    memory = AsyncMock()
    memory.records.return_value = [{
        "job_id": source_id, "request_text": "High Angle or Low Angle",
        "terms": [{"label_ko": "로우 앵글", "label_en": "low angle"}],
    }]
    snapshot = snapshot_factory([
        card_factory("view_low_angle", role="view"),
        card_factory("view_high_angle", role="view"),
    ])
    output = InterpretationOutput(
        interpretation_state="select_terms",
        selections=[InterpretationSelection(role="view", term_id="view_high_angle",
            evidence=["High Angle"], confidence=0.9, source_job_id=source_id)],
        context_updates=[ContextUpdate(role="view", term_id="view_high_angle", evidence=update_evidence)],
    )
    if update_evidence == "High Angle":
        asyncio.run(conversation_context.validate(memory, job, output, snapshot))
        assert output.context_updates[0].evidence == "High Angle"
    else:
        with pytest.raises(LLMInvalidStructuredOutput, match="조건 변경에 현재 요청의 명시적 근거가 필요합니다") as raised:
            asyncio.run(conversation_context.validate(memory, job, output, snapshot))
        assert raised.value.failure_code.value == "LLM_INVALID_STRUCTURED_OUTPUT"
    memory.records.assert_awaited_once_with(job, [output.selections[0].source_job_id])


@pytest.mark.parametrize("selections", [None, {}, "pose"])
def test_invalid_selection_type_is_still_rejected(selections):
    with pytest.raises(LLMInvalidStructuredOutput):
        _validate_output(json.dumps({"interpretation_state": "select_terms", "selections": selections}))


def test_v1_path_and_trace_version_can_be_activated_together():
    settings = Settings(_env_file=None, database_url="sqlite:///test.db",
                        interpreter_prompt_path=str(PROMPT), interpreter_prompt_version="uhkegryo-interpreter-v1")
    adapter = LLMInterpretationAdapter(client=object(), settings=settings)
    assert adapter.prompt_version == "uhkegryo-interpreter-v1"
    assert '"selections":[{' in adapter._system_message
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "COPY prompts/uhkegryo-interpreter-v1.md /app/prompts/uhkegryo-interpreter-v1.md" in dockerfile


def _historical_selection_case(snapshot_factory, card_factory, evidence):
    source_id = "00000000-0000-0000-0000-000000000001"
    job = {"request_text": "같은 구도를 다시 찾아줘"}
    memory = AsyncMock()
    memory.records.return_value = [{
        "job_id": source_id, "request_text": "Prior Low Angle",
        "terms": [{"label_ko": "이전 로우 앵글", "label_en": "low angle"}],
    }]
    output = InterpretationOutput(interpretation_state="select_terms", selections=[
        InterpretationSelection(role="view", term_id="view_low_angle", evidence=[evidence],
                                confidence=0.9, source_job_id=source_id),
    ])
    snapshot = snapshot_factory([card_factory("view_low_angle", role="view")])
    return memory, job, output, snapshot


@pytest.mark.parametrize("evidence", ["Prior Low Angle", "이전 로우 앵글", "low angle"])
def test_historical_selection_accepts_evidence_absent_from_current_request(snapshot_factory, card_factory, evidence):
    memory, job, output, snapshot = _historical_selection_case(snapshot_factory, card_factory, evidence)
    assert evidence not in job["request_text"]
    result = asyncio.run(conversation_context.validate(memory, job, output, snapshot))
    assert result.status == "proceed"
    assert result.terms[0].selection.evidence == [evidence]
    assert result.terms[0].selection.source_job_id == output.selections[0].source_job_id
    memory.records.assert_awaited_once_with(job, [output.selections[0].source_job_id])


@pytest.mark.parametrize("invalid", ["missing_source", "unknown_evidence", "inactive", "wrong_role", "no_source"])
def test_historical_selection_keeps_source_and_card_guards(snapshot_factory, card_factory, invalid):
    memory, job, output, snapshot = _historical_selection_case(snapshot_factory, card_factory, "Prior Low Angle")
    if invalid == "missing_source":
        memory.records.return_value[0]["job_id"] = "00000000-0000-0000-0000-000000000002"
    elif invalid == "unknown_evidence":
        output.selections[0].evidence = ["Not cited"]
    elif invalid == "inactive":
        snapshot = snapshot_factory([])
    elif invalid == "wrong_role":
        snapshot = snapshot_factory([card_factory("view_low_angle", role="pose")])
    else:
        output.selections[0].source_job_id = None
    with pytest.raises(LLMInvalidStructuredOutput) as raised:
        asyncio.run(conversation_context.validate(memory, job, output, snapshot))
    assert raised.value.failure_code.value == "LLM_INVALID_STRUCTURED_OUTPUT"


def test_resolver_requires_verified_texts_for_the_selected_source(snapshot_factory, card_factory):
    from backend.services.resolver import resolve
    _, job, output, snapshot = _historical_selection_case(snapshot_factory, card_factory, "Prior Low Angle")
    for sources in (None, {"00000000-0000-0000-0000-000000000002": ["Prior Low Angle"]}):
        result = resolve(output, snapshot, request_text=job["request_text"], verified_source_texts=sources)
        assert result.status == "all_invalid"


def test_v1_preserves_main_memory_instructions():
    from backend.services.llm import _extract_fenced_block
    baseline = (ROOT / "prompts/uhkegryo-interpreter-v0.md").read_text(encoding="utf-8")
    current = PROMPT.read_text(encoding="utf-8")
    for operation in ("classify", "summarize", "answer"):
        heading = "## Memory " + operation
        assert _extract_fenced_block(current, heading) == _extract_fenced_block(baseline, heading)
