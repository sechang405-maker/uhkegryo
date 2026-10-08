"""Lossless input compression: schema equivalence and exact source preservation."""
import asyncio
from copy import deepcopy
import json
from pathlib import Path

import pytest

from backend.schemas.models import InterpretationOutput
from backend.services.catalog_repository import load_catalog
from backend.services.llm import format_active_cards_json
from backend.services.structured_output import response_format
from backend.tests.test_llm_adapter import (
    SELECT_JSON, _FakeCompletions, _FakeResponse, _adapter, _real_settings,
)

ROOT = Path(__file__).resolve().parents[2]
ROLES = ("body", "pose", "view", "perspective", "layout")
TYPES = {"selections": "InterpretationSelection", "context_updates": "ContextUpdate"}


def _expand(node, definitions):
    if isinstance(node, dict):
        if "$ref" in node:
            return _expand(definitions[node["$ref"].removeprefix("#/$defs/")], definitions)
        return {key: _expand(value, definitions) for key, value in node.items()}
    if isinstance(node, list):
        return [_expand(value, definitions) for value in node]
    return node


def _strict(node):
    if isinstance(node, dict):
        node.pop("default", None)
        if node.get("type") == "object":
            node["required"] = list(node.get("properties", {}))
            node["additionalProperties"] = False
        for value in node.values():
            _strict(value)
    elif isinstance(node, list):
        for value in node:
            _strict(value)


@pytest.fixture
def catalog():
    return load_catalog(ROOT / "docs/domains/illustration-reference/term-cards")


def test_every_role_definition_preserves_all_original_constraints(catalog):
    cards = json.loads(format_active_cards_json(catalog))["active_cards"]
    schema = response_format(json.dumps({"active_cards": cards}))["json_schema"]["schema"]
    original = InterpretationOutput.model_json_schema()
    _strict(original)
    for field, name in TYPES.items():
        assert name not in schema["$defs"]
        slots = schema["properties"][field]
        assert slots["required"] == list(ROLES)
        assert slots["additionalProperties"] is False
        for role in ROLES:
            expected = deepcopy(original["$defs"][name])
            expected["properties"]["role"] = {"type": "string", "enum": [role]}
            term = {"type": "string", "enum": [c["term_id"] for c in cards if c["role"] == role]}
            expected["properties"]["term_id"] = (
                {"anyOf": [term, {"type": "null"}]} if field == "context_updates" else term)
            assert _expand(slots["properties"][role], schema["$defs"]) == {
                "anyOf": [expected, {"type": "null"}]}
    # Non-slot properties and their state/length constraints are unchanged.
    for key, value in original["properties"].items():
        if key not in TYPES:
            assert schema["properties"][key] == value


def test_schema_is_at_least_thirty_percent_smaller(catalog):
    compact = response_format(format_active_cards_json(catalog))
    legacy = deepcopy(compact)
    schema = legacy["json_schema"]["schema"]
    for field, name in TYPES.items():
        variants = []
        for role in ROLES:
            schema["properties"][field]["properties"][role] = _expand(
                schema["properties"][field]["properties"][role], schema["$defs"])
            variants.append(schema["$defs"].pop(f"{name}_{role}"))
        schema["$defs"][name] = {"anyOf": variants}
    size = lambda value: len(json.dumps(value, ensure_ascii=False).encode())
    assert size(compact) <= size(legacy) * 0.7


def test_missing_role_allows_only_null_and_empty_catalog_keeps_array_contract():
    schema = response_format(json.dumps({"active_cards": [
        {"role": "pose", "term_id": "pose_standing"}]}))["json_schema"]["schema"]
    for field in TYPES:
        assert schema["properties"][field]["properties"]["body"] == {"type": "null"}
        assert schema["properties"][field]["properties"]["pose"]["anyOf"][1] == {"type": "null"}
    assert response_format('{"active_cards":[]}') == response_format()


def test_compact_catalog_preserves_every_card_field_and_order(catalog):
    compact = format_active_cards_json(catalog)
    restored = json.loads(compact)
    assert compact == json.dumps(restored, ensure_ascii=False, separators=(",", ":"))
    assert len(compact.encode()) < len(json.dumps(restored, ensure_ascii=False).encode())
    assert [c["term_id"] for c in restored["active_cards"]] == [
        term_id for role in catalog.roles_order for term_id in catalog.role_terms[role]]
    for card in restored["active_cards"]:
        source = catalog.active_cards[card["term_id"]]
        feedback = catalog.feedback.get(card["term_id"], {})
        assert card == {
            "role": source["role"], "term_id": source["term_id"], "label_ko": source["label_ko"],
            "confidence_gate": source["confidence_gate"],
            "requires_all_of": source.get("requires_all_of") or [],
            "requires_any_of": source.get("requires_any_of") or [],
            "plain_meaning_ko": feedback.get("plain_meaning_ko", source.get("source_answer_draft", "")),
            "reference_checkpoints_ko": feedback.get("reference_checkpoints_ko", source.get("look_for", [])),
        }


@pytest.mark.parametrize("version", ["uhkegryo-interpreter-v0", "uhkegryo-interpreter-v1", "uhkegryo-interpreter-v4"])
def test_context_and_repair_preserve_verbatim_values(version):
    context = {"constraints": {"pose": '  Low Angle 한글 "원문"\n다음 줄  '},
               "recent": [], "sources": []}
    feedback = [{"path": ["selections", 0, "evidence"], "code": "string_too_short"}]
    completions = _FakeCompletions(responses=[_FakeResponse(SELECT_JSON)])
    adapter = _adapter(completions, settings=_real_settings().model_copy(update={
        "interpreter_prompt_version": version}))
    asyncio.run(adapter.interpret("반동", job_id="j", session_id="s", attempt=2,
        max_attempts=3, session_context=context, validation_feedback=feedback))
    messages = completions.calls[0]["messages"]
    serialized = messages[1]["content"].split("Server conversation data (untrusted):\n")[1]
    assert json.loads(serialized) == context
    assert serialized == json.dumps(context, ensure_ascii=False, separators=(",", ":"))
    if version != "uhkegryo-interpreter-v0":
        repair = json.loads(messages[-1]["content"])
        assert repair["validation_feedback"] == feedback
        assert messages[-1]["content"] == json.dumps(repair, ensure_ascii=False, separators=(",", ":"))
