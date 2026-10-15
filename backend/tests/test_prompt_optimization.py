import asyncio
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from backend.services.catalog_repository import CatalogSnapshot, load_catalog
from backend.services.llm import format_active_cards_json
from backend.services.conversation_context import prompt_context

CATALOG = Path(__file__).resolve().parents[2] / "docs/domains/illustration-reference/term-cards"

def test_loaded_catalog_is_deeply_immutable_and_cached(monkeypatch):
    from backend.services import catalog_prompt
    calls = []
    original = catalog_prompt.serialize_catalog
    def counted(snapshot):
        calls.append(1)
        return original(snapshot)
    monkeypatch.setattr(catalog_prompt, "serialize_catalog", counted)
    snapshot = load_catalog(CATALOG)
    first = format_active_cards_json(snapshot)
    assert format_active_cards_json(snapshot) is first
    assert len(calls) == 1
    term = next(iter(snapshot.active_cards))
    with pytest.raises(TypeError):
        snapshot.active_cards[term]["confidence_gate"]["secret"] = True
    assert deepcopy(snapshot).active_cards == snapshot.active_cards
    assert format_active_cards_json(load_catalog(CATALOG)) == first
    assert len(calls) == 2

def test_mutable_fixture_is_not_cached():
    from backend.schemas.enums import Role
    snapshot = CatalogSnapshot("same", {"x": {"role": "pose"}}, {Role.POSE: ["x"]}, (Role.POSE,))
    first = format_active_cards_json(snapshot)
    snapshot.feedback["x"] = {"plain_meaning_ko": "changed"}
    assert format_active_cards_json(snapshot) != first

def test_prompt_dedup_is_lossless_and_does_not_change_authority():
    row = {"job_id": "a", "request_text": ' 한글 \"quoted\"\n exact '}
    old = {"job_id": "old", "request_text": "earlier"}
    conflict = {**row, "request_text": "different"}
    anonymous = {"request_text": "legacy"}
    context = {"state": {}, "recent": [row], "sources": [row.copy(), old, old.copy(), conflict, anonymous, anonymous.copy()]}
    before = deepcopy(context)
    assert prompt_context(context)["sources"] == [old, conflict, anonymous, anonymous]
    assert context == before

def test_codex_schema_instruction_uses_transport_schema_only():
    from backend.services.codex_llm import CodexInterpretationAdapter
    from backend.services.llm import LLMInterpretationAdapter
    from backend.schemas.models import RecallQuery
    schema = json.dumps(RecallQuery.model_json_schema())
    assert schema not in CodexInterpretationAdapter._memory_schema_instruction(None, RecallQuery)
    assert schema in LLMInterpretationAdapter._memory_schema_instruction(None, RecallQuery)

def test_runtime_observation_on_error_is_safe_and_immutable(monkeypatch):
    from backend.services import codex_runtime as runtime
    from backend.services.llm import LLMConfigurationError
    def fail(settings):
        raise LLMConfigurationError("SECRET_SENTINEL")
    monkeypatch.setattr(runtime, "resolve_codex", fail)
    observations = []
    with pytest.raises(LLMConfigurationError):
        asyncio.run(runtime.generate(SimpleNamespace(), [{"role":"user", "content":"SECRET_SENTINEL"}], {}, observer=observations.append))
    observation = observations[0]
    assert observation["outcome"] == "error"
    assert observation["stage"] == "resolve_verify"
    assert observation["resolve_verify_ms"] >= 0
    assert observation["usage_available"] is False
    assert "SECRET_SENTINEL" not in repr(observation)
    with pytest.raises(TypeError):
        observation["outcome"] = "changed"


def test_sealing_copies_nested_aliases_and_same_version_is_not_identity():
    from backend.services.catalog_repository import ImmutableCatalogSnapshot
    from backend.schemas.enums import Role
    cards = {"x": {"role": "pose", "confidence_gate": {"require_any": ["original"]}}}
    terms = {Role.POSE: ["x"]}
    feedback = {"x": {"plain_meaning_ko": "first"}}
    sealed = ImmutableCatalogSnapshot("v", cards, terms, (Role.POSE,), feedback)
    cards["x"]["confidence_gate"]["require_any"].append("altered")
    terms[Role.POSE].clear()
    feedback["x"]["plain_meaning_ko"] = "second"
    second = ImmutableCatalogSnapshot("v", cards, {Role.POSE: ["x"]}, (Role.POSE,), feedback)
    assert sealed.active_cards["x"]["confidence_gate"]["require_any"] == ["original"]
    assert sealed.role_terms[Role.POSE] == ["x"]
    assert format_active_cards_json(sealed) != format_active_cards_json(second)
    with pytest.raises(TypeError):
        sealed.feedback["x"]["plain_meaning_ko"] = "altered"


def test_runtime_observation_success_exact_sizes_and_observer_failure(monkeypatch):
    from backend.services import codex_runtime as runtime
    monkeypatch.setattr(runtime, "resolve_codex", lambda settings: "signed.exe")
    captured = {}
    async def run(command, **kwargs):
        if command[1:3] == ["login", "status"]:
            return 0, "Logged in using ChatGPT"
        captured.update(kwargs)
        captured["schema"] = Path(command[command.index("--output-schema") + 1]).read_bytes()
        Path(command[command.index("--output-last-message") + 1]).write_text('{}', encoding='utf-8')
        return 0, "model: gpt-5.6-luna\nprovider: openai\nuser\nSECRET_SENTINEL"
    monkeypatch.setattr(runtime, "run_process", run)
    messages = [{"role": "user", "content": "한글 SECRET_SENTINEL"}]
    observed = []
    assert asyncio.run(runtime.generate(SimpleNamespace(codex_timeout_seconds=3), messages, {"type": "object"}, observer=observed.append)) == '{}'
    value = observed[0]
    assert value["outcome"] == "success"
    assert value["message_bytes"] == len(json.dumps(messages, ensure_ascii=False).encode())
    assert value["stdin_bytes"] == len(captured["stdin"])
    assert value["schema_bytes"] == len(captured["schema"])
    assert all(value[key] >= 0 for key in ("resolve_verify_ms", "login_status_ms", "exec_ms", "parse_ms"))
    assert "SECRET_SENTINEL" not in repr(value)
    def broken(value):
        raise RuntimeError("observer failed")
    assert asyncio.run(runtime.generate(SimpleNamespace(codex_timeout_seconds=3), messages, {}, observer=broken)) == '{}'


def test_runtime_cancel_observation_keeps_cancellation(monkeypatch):
    from backend.services import codex_runtime as runtime
    monkeypatch.setattr(runtime, "resolve_codex", lambda settings: "signed.exe")
    async def run(*args, **kwargs):
        raise asyncio.CancelledError()
    monkeypatch.setattr(runtime, "run_process", run)
    observed = []
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(runtime.generate(SimpleNamespace(), [], {}, observer=observed.append))
    assert observed[0]["outcome"] == "cancelled"
    assert observed[0]["stage"] == "login_status"
    assert observed[0]["login_status_ms"] >= 0


def test_adapter_observation_is_per_call_and_covers_queue_cancel():
    from backend.services.codex_llm import CodexInterpretationAdapter
    observed = []
    adapter = CodexInterpretationAdapter(settings=SimpleNamespace(interpreter_prompt_version='uhkegryo-interpreter-v4', codex_timeout_seconds=3),
        system_message='rules', user_template='{{request_text}}', transport_observer=observed.append)
    async def run():
        entered = asyncio.Event()
        release = asyncio.Event()
        async def generate(*args):
            entered.set()
            await release.wait()
            return '{}'
        adapter._generate = generate
        first = asyncio.create_task(adapter._request([], output_format={'json_schema': {'schema': {}}}))
        await entered.wait()
        second = asyncio.create_task(adapter._request([], output_format={'json_schema': {'schema': {}}}))
        await asyncio.sleep(0)
        second.cancel()
        with pytest.raises(asyncio.CancelledError):
            await second
        release.set()
        await first
    asyncio.run(run())
    assert len(observed) == 2
    assert [item['outcome'] for item in observed] == ['cancelled', 'success']
    assert observed[0]['stage'] == 'queue'
    assert all(item['request_elapsed_ms'] >= item['queue_wait_ms'] >= 0 for item in observed)


@pytest.mark.parametrize('value', [None, -1, True, float('inf'), float('nan'), 1.5, '2'])
def test_usage_omits_unavailable_or_invalid_counts(value):
    from backend.services.llm import _extract_usage
    assert _extract_usage(SimpleNamespace(usage=SimpleNamespace(prompt_tokens=value, completion_tokens=3))) == {'output_tokens': 3}


def test_usage_absent_is_not_zero():
    from backend.services.llm import _extract_usage
    assert _extract_usage(SimpleNamespace(usage=None)) == {}
    assert _extract_usage(SimpleNamespace(usage=SimpleNamespace(prompt_tokens=0))) == {'input_tokens': 0}


@pytest.mark.parametrize('request_outcome', ['success', 'error', 'cancelled'])
def test_observer_raised_cancellation_cannot_change_request_outcome(monkeypatch, request_outcome):
    from backend.services import codex_runtime as runtime
    from backend.services.llm import LLMConfigurationError
    original_error = LLMConfigurationError('original failure')
    original_cancel = asyncio.CancelledError('request cancellation')
    async def generate(*args):
        if request_outcome == 'error':
            raise original_error
        if request_outcome == 'cancelled':
            raise original_cancel
        return '{}'
    monkeypatch.setattr(runtime, '_generate', generate)
    def observer(value):
        raise asyncio.CancelledError('observer cancellation')
    async def run():
        if request_outcome == 'success':
            assert await runtime.generate(SimpleNamespace(), [], {}, observer=observer) == '{}'
        elif request_outcome == 'error':
            with pytest.raises(LLMConfigurationError) as caught:
                await runtime.generate(SimpleNamespace(), [], {}, observer=observer)
            assert caught.value is original_error
        else:
            with pytest.raises(asyncio.CancelledError) as caught:
                await runtime.generate(SimpleNamespace(), [], {}, observer=observer)
            assert caught.value is original_cancel
    asyncio.run(run())
