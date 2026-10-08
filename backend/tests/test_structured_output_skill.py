import asyncio
import json
import sys
from pathlib import Path

import pytest

from backend.services import llm
from backend.services.structured_output import response_format
from backend.tests.test_llm_adapter import (
    CLARIFY_JSON, SELECT_JSON, _FakeClient, _FakeCompletions, _FakeResponse, _adapter, _real_settings,
    _langfuse_generation_kwargs,
)

ROOT = Path(__file__).resolve().parents[2]
PROMPT = ROOT / "prompts" / "uhkegryo-interpreter-v1.md"


def test_catalog_schema_limits_term_ids_to_their_role():
    cards = json.dumps({"active_cards": [
        {"role": "view", "term_id": "view_front"},
        {"role": "layout", "term_id": "layout_center"},
    ]})
    definitions = response_format(cards)["json_schema"]["schema"]["$defs"]
    for name in ("InterpretationSelection", "ContextUpdate"):
        variants = [definitions[f"{name}_{role}"] for role in ("view", "layout")]
        assert len(variants) == 2
        for variant in variants:
            properties = variant["properties"]
            role = properties["role"]["enum"][0]
            term = properties["term_id"]
            if name == "ContextUpdate":
                assert term["anyOf"][1] == {"type": "null"}
                term = term["anyOf"][0]
            assert term["enum"] == ["view_front" if role == "view" else "layout_center"]
            assert variant["additionalProperties"] is False


def test_generation_stays_open_during_upstream_call(monkeypatch):
    recorded, _ = _langfuse_generation_kwargs(monkeypatch)
    events = []
    fake = sys.modules["langfuse"].Langfuse
    original = fake.start_as_current_observation
    from contextlib import contextmanager

    @contextmanager
    def observation(self, **kwargs):
        events.append("start")
        with original(self, **kwargs) as generation:
            yield generation
        events.append("end")

    monkeypatch.setattr(fake, "start_as_current_observation", observation)

    class Completions(_FakeCompletions):
        async def create(self, **kwargs):
            assert events == ["start"]
            events.append("call")
            await asyncio.sleep(0.01)
            return await super().create(**kwargs)

    settings = _real_settings().model_copy(update={
        "langfuse_public_key": "pk-test", "langfuse_secret_key": "sk-test",
    })
    adapter = _adapter(Completions(responses=[_FakeResponse(SELECT_JSON)]), settings=settings)
    asyncio.run(adapter.interpret("반동", job_id="j", session_id="s", attempt=1, max_attempts=3))
    assert events == ["start", "call", "end"]
    assert recorded["generation_update"]["usage_details"]["total_tokens"] == 15


@pytest.mark.parametrize("wrong_role", [False, True, "clarify"])
def test_v4_role_slots_convert_to_existing_array_contract(wrong_role):
    payload = json.loads(CLARIFY_JSON if wrong_role == "clarify" else SELECT_JSON)
    roles = ("body", "pose", "view", "perspective", "layout")
    payload["selections"] = dict.fromkeys(roles)
    payload["selections"]["pose"] = {
        "role": "view" if wrong_role else "pose", "term_id": "pose_contrapposto",
        "evidence": ["반동"], "confidence": 0.9, "source_job_id": None,
    }
    if wrong_role == "clarify":
        payload["selections"]["pose"] = None
    payload["context_updates"] = dict.fromkeys(roles)
    completions = _FakeCompletions(responses=[_FakeResponse(json.dumps(payload))])
    adapter = _adapter(completions, settings=_real_settings().model_copy(update={
        "interpreter_prompt_version": "uhkegryo-interpreter-v4"}))
    call = adapter.interpret("반동", job_id="j", session_id="s", attempt=1, max_attempts=3,
        active_cards_json=json.dumps({"active_cards": [{"role": "pose", "term_id": "pose_contrapposto"}]}))
    if wrong_role is True:
        with pytest.raises(llm.LLMInvalidStructuredOutput):
            asyncio.run(call)
    else:
        output = asyncio.run(call)
        assert len(output.selections) == (0 if wrong_role == "clarify" else 1)
        assert output.context_updates == []


def test_schema_preserves_code_types_and_requires_nullable_fields():
    schema = response_format()["json_schema"]["schema"]
    assert set(schema["required"]) == set(schema["properties"])
    assert schema["additionalProperties"] is False
    assert schema["properties"]["selections"]["type"] == "array"
    selection = schema["$defs"]["InterpretationSelection"]
    assert set(selection["required"]) == set(selection["properties"])
    assert {"role", "term_id", "evidence", "confidence", "source_job_id"} <= set(selection["required"])
    assert selection["properties"]["confidence"]["minimum"] == 0
    assert selection["properties"]["confidence"]["maximum"] == 1
    assert {item["type"] for item in schema["properties"]["clarifying_question"]["anyOf"]} == {"string", "null"}


@pytest.mark.parametrize("version", ["uhkegryo-interpreter-v1", "uhkegryo-interpreter-v4"])
def test_duplicate_role_feedback_is_used_on_next_single_call(version):
    payload = json.loads(SELECT_JSON)
    payload["selections"].append(payload["selections"][0].copy())
    completions = _FakeCompletions(responses=[_FakeResponse(json.dumps(payload)), _FakeResponse(SELECT_JSON)])
    adapter = _adapter(completions, settings=_real_settings().model_copy(update={
        "interpreter_prompt_version": version,
    }))
    kwargs = dict(job_id="job-1", session_id="session-1", max_attempts=3)
    with pytest.raises(llm.LLMInvalidStructuredOutput) as raised:
        asyncio.run(adapter.interpret("반동", attempt=1, **kwargs))
    assert raised.value.feedback == [{"path": [], "code": "role_duplicate"}]
    output = asyncio.run(adapter.interpret("반동", attempt=2, validation_feedback=raised.value.feedback, **kwargs))
    assert len(output.selections) == 1 and len(completions.calls) == 2
    sent = completions.calls[1]["messages"]
    assert sum(item["role"] == "system" for item in sent) == 1
    repair = json.loads(sent[-1]["content"])
    assert repair["validation_feedback"] == raised.value.feedback
    if version == "uhkegryo-interpreter-v4":
        assert "pose_sitting" in repair["repair_rules"] and "pose_gesture" in repair["repair_rules"]
    else:
        assert repair == {"validation_feedback": raised.value.feedback}


def test_feedback_never_contains_unknown_field_names_or_input_values():
    payload = json.loads(SELECT_JSON)
    payload["secret-field-marker"] = "secret-value-marker"
    with pytest.raises(llm.LLMInvalidStructuredOutput) as raised:
        llm._validate_output(json.dumps(payload))
    assert raised.value.feedback == [{"path": ["unknown_field"], "code": "extra_forbidden"}]
    assert "secret" not in json.dumps(raised.value.feedback)


def test_missing_skill_fails_before_call():
    settings = _real_settings().model_copy(update={"structured_output_skill_path": "missing-skill.md",
                                                 "interpreter_prompt_version": "uhkegryo-interpreter-v1"})
    with pytest.raises(llm.PromptConfigurationError):
        llm.LLMInterpretationAdapter(settings=settings, client=object(),
                                    prompt_path=PROMPT)


def test_v1_call_combines_interpreter_and_output_instructions():
    settings = _real_settings().model_copy(update={
        "interpreter_prompt_path": str(PROMPT),
        "interpreter_prompt_version": "uhkegryo-interpreter-v1",
    })
    completions = _FakeCompletions(responses=[_FakeResponse(SELECT_JSON)])
    adapter = llm.LLMInterpretationAdapter(settings=settings, client=_FakeClient(completions))
    asyncio.run(adapter.interpret("반동", job_id="j", session_id="s", attempt=1, max_attempts=3))
    call = completions.calls[0]
    messages = call["messages"]
    system = messages[0]["content"]
    assert sum(item["role"] == "system" for item in messages) == 1
    assert system.startswith(llm.load_interpreter_prompt(PROMPT)[0])
    assert "role_duplicate" in system
    assert call["response_format"] == response_format()
    assert call["extra_body"] == {"provider": {"require_parameters": True}}
    assert adapter.prompt_version == "uhkegryo-interpreter-v1"
    for rule in ("Return exactly one JSON object", "Include every field", "always arrays",
                 "For select_terms:", "For needs_clarification:", "Selection shape example:",
                 "Clarification shape example:"):
        assert system.count(rule) == 1


def test_v0_keeps_json_mode_without_skill_or_feedback():
    prompt = ROOT / "prompts/uhkegryo-interpreter-v0.md"
    settings = _real_settings().model_copy(update={"structured_output_skill_path": "missing.md"})
    completions = _FakeCompletions(responses=[_FakeResponse(SELECT_JSON)])
    adapter = llm.LLMInterpretationAdapter(settings=settings, prompt_path=prompt, client=_FakeClient(completions))
    asyncio.run(adapter.interpret("반동", job_id="j", session_id="s", attempt=1, max_attempts=3,
                                  validation_feedback=[{"path": [], "code": "role_duplicate"}]))
    call = completions.calls[0]
    assert adapter.prompt_version == "uhkegryo-interpreter-v0"
    assert call["messages"][0]["content"].startswith(llm.load_interpreter_prompt(prompt)[0] + "\n")
    assert "Include answer_text" in call["messages"][0]["content"]
    assert len(call["messages"]) == 2 and len(completions.calls) == 1
    assert call["response_format"] == {"type": "json_object"} and "extra_body" not in call


@pytest.mark.parametrize("content", ["raw-secret", json.dumps({
    **json.loads(SELECT_JSON), **{f"raw-secret-{i}": "raw-secret" for i in range(12)},
})])
@pytest.mark.parametrize("version", ["uhkegryo-interpreter-v0", "uhkegryo-interpreter-v1"])
def test_validation_failure_generation_is_bounded_and_has_no_raw_data(monkeypatch, caplog, content, version):
    recorded, _ = _langfuse_generation_kwargs(monkeypatch)
    settings = _real_settings().model_copy(update={"langfuse_public_key": "pk-test",
        "langfuse_secret_key": "sk-test", "interpreter_prompt_version": version})
    adapter = _adapter(_FakeCompletions(responses=[_FakeResponse(content)]), settings=settings)
    with caplog.at_level("DEBUG"), pytest.raises(llm.LLMInvalidStructuredOutput) as raised:
        asyncio.run(adapter.interpret("request-secret", job_id="j", session_id="s", attempt=2, max_attempts=3))
    generation, update = recorded["generation"], recorded["generation_update"]
    assert recorded["parent_trace_id"] == "worker-owned-trace"
    assert generation["input"] is None and update["output"] is None
    assert update["level"] == "ERROR" and update["usage_details"]["total_tokens"] == 15
    assert generation["metadata"] == {"job_id": "j", "session_id": "s", "attempt": 2, "max_attempts": 3,
        "error_type": "pydantic_validation_error", "validation_feedback": raised.value.feedback}
    assert len(raised.value.feedback) == (8 if content.startswith("{") else 1)
    serialized = json.dumps(recorded) + caplog.text
    assert "request-secret" not in serialized and "raw-secret" not in serialized


@pytest.mark.parametrize("mode", ["no_worker_trace", "sdk_failure"])
def test_failed_generation_observation_does_not_change_validation_failure(monkeypatch, caplog, mode):
    recorded, _ = _langfuse_generation_kwargs(monkeypatch)
    fake = sys.modules["langfuse"].Langfuse
    if mode == "no_worker_trace":
        monkeypatch.setattr(fake, "get_current_trace_id", lambda self: None)
    else:
        def fail(self, **kwargs):
            raise RuntimeError("sdk-secret-exception")
        monkeypatch.setattr(fake, "start_as_current_observation", fail)
    recorded.clear()
    settings = _real_settings().model_copy(update={"langfuse_public_key": "pk-test", "langfuse_secret_key": "sk-test"})
    adapter = _adapter(_FakeCompletions(responses=[_FakeResponse("raw-secret")]), settings=settings)
    with caplog.at_level("DEBUG"), pytest.raises(llm.LLMInvalidStructuredOutput) as raised:
        asyncio.run(adapter.interpret("request-secret", job_id="j", session_id="s", attempt=1, max_attempts=3))
    assert raised.value.feedback == [{"path": [], "code": "json_invalid"}]
    assert "generation" not in recorded
    assert all(secret not in caplog.text for secret in ("sdk-secret-exception", "request-secret", "raw-secret"))
