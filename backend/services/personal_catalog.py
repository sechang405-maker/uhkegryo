"""Owner-scoped personal cards overlaid on the immutable shared catalog per job."""

from __future__ import annotations

from collections.abc import Iterable

from backend.schemas.enums import Role
from backend.services.catalog_repository import CatalogSnapshot


def with_personal_terms(
    snapshot: CatalogSnapshot, records: Iterable[object],
) -> CatalogSnapshot:
    """Return a request-local snapshot containing only supplied active personal terms."""
    active_cards = dict(snapshot.active_cards)
    role_terms = {role: list(term_ids) for role, term_ids in snapshot.role_terms.items()}
    feedback = dict(snapshot.feedback)

    for record in records:
        if getattr(record, "status", None) != "active":
            continue
        term_id = str(record.term_id)
        role = Role(record.role)
        active_cards[term_id] = {
            "term_id": term_id,
            "role": role.value,
            "label_ko": record.label_ko,
            "label_en": record.label_en,
            "query_fragments": list(record.query_fragments_en),
            "look_for": list(record.reference_checkpoints_ko),
            "confidence_gate": {},
            "requires_all_of": [],
            "requires_any_of": [],
            "source_type": "personal_term",
            "source_answer_draft": record.plain_meaning_ko,
            "aliases_ko": list(record.aliases_ko),
        }
        if term_id not in role_terms.setdefault(role, []):
            role_terms[role].append(term_id)
        feedback[term_id] = {
            "plain_meaning_ko": record.plain_meaning_ko,
            "selection_reason_template_ko": "내가 저장한 개인 용어",
            "reference_checkpoints_ko": list(record.reference_checkpoints_ko),
        }

    return CatalogSnapshot(
        dataset_version=snapshot.dataset_version,
        active_cards=active_cards,
        role_terms=role_terms,
        roles_order=snapshot.roles_order,
        feedback=feedback,
        direct_search_disabled=snapshot.direct_search_disabled,
    )
