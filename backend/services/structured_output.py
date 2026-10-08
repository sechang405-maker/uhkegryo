"""Code-derived output schema and bounded, non-sensitive validation feedback."""
from pathlib import Path
import json

from backend.schemas.models import InterpretationOutput


def response_format(active_cards_json: str = "") -> dict:
    schema = InterpretationOutput.model_json_schema()

    def strict(node):
        if isinstance(node, dict):
            node.pop("default", None)
            if node.get("type") == "object":
                node["required"] = list(node.get("properties", {}))
                node["additionalProperties"] = False
            for value in node.values():
                strict(value)
        elif isinstance(node, list):
            for value in node:
                strict(value)

    strict(schema)
    if active_cards_json:
        cards = json.loads(active_cards_json).get("active_cards", [])
        for name in ("InterpretationSelection", "ContextUpdate"):
            original = schema["$defs"][name]
            references = {}
            for role in ("body", "pose", "view", "perspective", "layout"):
                ids = [c["term_id"] for c in cards if c["role"] == role]
                if not ids:
                    continue
                variant = json.loads(json.dumps(original))
                variant["properties"]["role"] = {"type": "string", "enum": [role]}
                term = {"type": "string", "enum": ids}
                variant["properties"]["term_id"] = (
                    {"anyOf": [term, {"type": "null"}]} if name == "ContextUpdate" else term
                )
                definition = f"{name}_{role}"
                schema["$defs"][definition] = variant
                references[role] = {"$ref": f"#/$defs/{definition}"}
            if references:
                del schema["$defs"][name]
                field = "selections" if name == "InterpretationSelection" else "context_updates"
                slots = {role: {"anyOf": [references[role], {"type": "null"}]}
                    if role in references else {"type": "null"}
                    for role in ("body", "pose", "view", "perspective", "layout")}
                schema["properties"][field] = {"type": "object", "properties": slots,
                    "required": list(slots), "additionalProperties": False,
                    "description": "One nullable slot per role. Direction takes priority over full-body framing in view."}
    return {"type": "json_schema", "json_schema": {
        "name": "interpretation_output", "strict": True, "schema": schema,
    }}


def validation_feedback(error) -> list[dict]:
    schema = InterpretationOutput.model_json_schema()
    fields = set(schema["properties"]) | {
        field for definition in schema.get("$defs", {}).values()
        for field in definition.get("properties", {})
    }
    feedback = []
    for item in error.errors(include_input=False, include_url=False)[:8]:
        code = item["type"]
        if not item["loc"]:
            message = item["msg"]
            code = "role_duplicate" if "역할당 최대" in message else "role_order" if "역할 순서" in message else "state_rules"
        path = [part if isinstance(part, int) or part in fields else "unknown_field" for part in item["loc"]]
        feedback.append({"path": path, "code": code})
    return feedback


def load_skill(path: str) -> str:
    from backend.services.llm import _extract_fenced_block

    return _extract_fenced_block(Path(path).read_text(encoding="utf-8"), "## Runtime instructions")
