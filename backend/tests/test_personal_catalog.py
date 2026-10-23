from types import SimpleNamespace

from backend.schemas.enums import Role
from backend.services.personal_catalog import with_personal_terms


def record(term_id: str, *, status: str):
    return SimpleNamespace(
        term_id=term_id,
        status=status,
        role=Role.POSE,
        label_ko="개인 자세",
        label_en="personal pose",
        plain_meaning_ko="사용자가 저장한 개인 자세 설명",
        reference_checkpoints_ko=["개인 자세의 기준점"],
        aliases_ko=["내 자세"],
        query_fragments_en=["personal pose reference"],
    )


def test_personal_catalog_overlay_includes_only_active_records(snapshot_factory):
    shared = snapshot_factory([])

    overlaid = with_personal_terms(shared, [
        record("personal_active", status="active"),
        record("personal_proposed", status="proposed"),
        record("personal_deleted", status="deleted"),
    ])

    assert set(overlaid.active_cards) == {"personal_active"}
    assert overlaid.role_terms[Role.POSE] == ["personal_active"]
    assert overlaid.feedback["personal_active"]["plain_meaning_ko"] == "사용자가 저장한 개인 자세 설명"
    assert shared.active_cards == {}
    assert shared.role_terms.get(Role.POSE, []) == []
