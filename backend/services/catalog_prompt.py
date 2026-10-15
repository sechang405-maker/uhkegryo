"""Lossless catalog projection shared by loading and prompt rendering."""
import json
from collections.abc import Mapping
from typing import Any

def plain(value):
    if isinstance(value, Mapping):
        return {key: plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(item) for item in value]
    return value

def serialize_catalog(snapshot):
    active_cards: list[dict[str, Any]] = []
    for role in snapshot.roles_order:
        for term_id in snapshot.role_terms.get(role, []):
            card = snapshot.active_cards.get(term_id, {})
            if card.get('component') == 'composite':
                continue  # Historical results remain readable; new selections use independent cards.
            feedback = snapshot.feedback.get(term_id, {})
            active_cards.append(
                {
                    "role": card.get("role"),
                    "term_id": term_id,
                    "label_ko": card.get("label_ko"),
                    "confidence_gate": card.get("confidence_gate"),
                    "requires_all_of": card.get("requires_all_of") or [],
                    "requires_any_of": card.get("requires_any_of") or [],
                    "plain_meaning_ko": feedback.get("plain_meaning_ko", card.get("source_answer_draft", "")),
                    "reference_checkpoints_ko": feedback.get("reference_checkpoints_ko", card.get("look_for", [])),
                }
            )
    return json.dumps(plain({"active_cards": active_cards}), ensure_ascii=False, separators=(",", ":"))
