from __future__ import annotations

import asyncio

import pytest
from pydantic import ValidationError

from backend.schemas.personal_terms import PersonalTermDraft, PersonalTermUpdate
from backend.services.personal_term_repository import (
    PersonalTermIdempotencyConflict,
    PersonalTermNotFound,
    PersonalTermRepository,
    PersonalTermStateConflict,
)
from backend.services.session_repository import SessionRepository
from backend.tests.test_conversation_sessions import database_case


def draft(**overrides) -> PersonalTermDraft:
    values = {
        "role": "pose",
        "label_ko": "나만의 비틀린 자세",
        "label_en": "personal twisted pose",
        "plain_meaning_ko": "몸통과 골반의 방향 차이를 강조한 개인 포즈 용어예요.",
        "reference_checkpoints_ko": ["몸통과 골반의 축이 서로 다르게 보이는지 확인"],
        "cautions_ko": ["관절을 과도하게 꺾지 않기"],
        "aliases_ko": ["비틀림 포즈"],
        "query_fragments_en": ["twisted torso pose reference"],
        "source_input": "몸통과 골반이 반대로 비틀린 자세를 내 용어로 저장하고 싶어",
        "proposal_kind": "descriptive",
        "uncertainty_ko": None,
    }
    values.update(overrides)
    return PersonalTermDraft(**values)


def test_personal_term_input_rejects_invalid_or_unbounded_text():
    with pytest.raises(ValidationError):
        draft(role="background")
    with pytest.raises(ValidationError):
        draft(label_ko="   ")
    with pytest.raises(ValidationError):
        draft(source_input="x" * 301)
    with pytest.raises(ValidationError):
        PersonalTermUpdate(label_ko="", unexpected=True)


def test_personal_terms_are_owner_scoped_idempotent_and_persistent():
    async def case(pool):
        sessions = SessionRepository(pool)
        repository = PersonalTermRepository(pool)
        session_a = await sessions.create_session("owner-a")
        session_b = await sessions.create_session("owner-b")

        created, was_created = await repository.create_proposal(
            "owner-a", draft(), idempotency_key="proposal-key", input_hash="input-v1"
        )
        with pytest.raises(PersonalTermNotFound):
            await repository.get_active_term("owner-a", created.term_id)
        repeated, repeated_created = await repository.create_proposal(
            "owner-a", draft(), idempotency_key="proposal-key", input_hash="input-v1"
        )

        assert was_created is True
        assert repeated_created is False
        assert repeated.personal_term_id == created.personal_term_id
        assert created.term_id.startswith("personal_")
        assert created.status == "proposed"
        assert await repository.list_terms("owner-b", include_deleted=True) == []
        with pytest.raises(PersonalTermNotFound):
            await repository.get_term("owner-b", created.term_id, include_deleted=True)
        with pytest.raises(PersonalTermIdempotencyConflict):
            await repository.create_proposal(
                "owner-a", draft(source_input="다른 입력"),
                idempotency_key="proposal-key", input_hash="input-v2",
            )

        updated = await repository.update_term(
            "owner-a", created.term_id,
            PersonalTermUpdate(label_ko="내 비틀림 자세"),
        )
        assert updated.label_ko == "내 비틀림 자세"
        with pytest.raises(PersonalTermNotFound):
            await repository.update_term(
                "owner-b", created.term_id, PersonalTermUpdate(label_ko="가로채기")
            )

        active = await repository.confirm_term("owner-a", created.term_id)
        assert active.status == "active"
        assert active.layout_slot == 0
        assert (await repository.get_active_term("owner-a", created.term_id)).term_id == created.term_id
        assert [term.term_id for term in await repository.list_active_terms_for_session(
            str(session_a)
        )] == [created.term_id]
        assert await repository.list_active_terms_for_session(str(session_b)) == []
        with pytest.raises(PersonalTermNotFound):
            await repository.get_active_term("owner-b", created.term_id)
        with pytest.raises(PersonalTermStateConflict):
            await repository.update_term(
                "owner-a", created.term_id, PersonalTermUpdate(role="composition")
            )

        replacement_session_a = await sessions.create_session("owner-a")
        assert [term.term_id for term in await repository.list_terms("owner-a")] == [created.term_id]
        await sessions.delete_session("owner-a", session_a)
        assert (await repository.get_term("owner-a", created.term_id)).status == "active"

        deleted = await repository.soft_delete("owner-a", created.term_id)
        assert deleted.status == "deleted" and deleted.deleted_at is not None
        repeated_delete = await repository.soft_delete("owner-a", created.term_id)
        assert repeated_delete.status == "deleted"
        assert repeated_delete.layout_slot == active.layout_slot
        with pytest.raises(PersonalTermNotFound):
            await repository.get_active_term("owner-a", created.term_id)
        assert await repository.list_terms("owner-a") == []
        assert await repository.list_active_terms_for_session(str(replacement_session_a)) == []
        with pytest.raises(PersonalTermNotFound):
            await repository.soft_delete("owner-b", created.term_id)

        restored = await repository.restore_term("owner-a", created.term_id)
        assert restored.status == "active"
        assert restored.term_id == active.term_id
        assert restored.layout_slot == active.layout_slot
        repeated_restore = await repository.restore_term("owner-a", created.term_id)
        assert repeated_restore.status == "active"
        assert repeated_restore.layout_slot == active.layout_slot
        assert [term.term_id for term in await repository.list_active_terms_for_session(
            str(replacement_session_a)
        )] == [created.term_id]

        proposed, _ = await repository.create_proposal(
            "owner-a", draft(label_ko="restore proposed"),
            idempotency_key="proposal-to-restore", input_hash="proposal-to-restore",
        )
        assert (await repository.soft_delete("owner-a", proposed.term_id)).status == "deleted"
        restored_proposed = await repository.restore_term("owner-a", proposed.term_id)
        assert restored_proposed.status == "proposed"
        assert restored_proposed.layout_slot is None
        assert [term.term_id for term in await repository.list_active_terms_for_session(
            str(replacement_session_a)
        )] == [created.term_id]

        generating, _ = await repository.begin_generation(
            "owner-a", "still generating", idempotency_key="generating-delete",
            input_hash="generating-delete",
        )
        with pytest.raises(PersonalTermStateConflict):
            await repository.soft_delete("owner-a", generating.term_id)

    asyncio.run(database_case(case))


def test_unknown_owner_cannot_create_or_discover_terms():
    async def case(pool):
        repository = PersonalTermRepository(pool)
        with pytest.raises(PersonalTermNotFound):
            await repository.create_proposal(
                "unknown-cookie", draft(), idempotency_key="unknown-key", input_hash="unknown-input"
            )
        assert await repository.list_terms("unknown-cookie", include_deleted=True) == []

    asyncio.run(database_case(case))


def test_concurrent_confirmation_serializes_slots_per_owner():
    async def case(pool):
        sessions = SessionRepository(pool)
        repository = PersonalTermRepository(pool)
        await sessions.create_session("owner-a")
        await sessions.create_session("owner-b")

        a_first, _ = await repository.create_proposal(
            "owner-a", draft(label_ko="첫 자세"),
            idempotency_key="owner-a-first", input_hash="owner-a-first",
        )
        a_second, _ = await repository.create_proposal(
            "owner-a", draft(label_ko="둘째 자세"),
            idempotency_key="owner-a-second", input_hash="owner-a-second",
        )
        b_first, _ = await repository.create_proposal(
            "owner-b", draft(label_ko="다른 소유자 자세"),
            idempotency_key="owner-b-first", input_hash="owner-b-first",
        )

        confirmed_a_first, confirmed_a_second, confirmed_b = await asyncio.gather(
            repository.confirm_term("owner-a", a_first.term_id),
            repository.confirm_term("owner-a", a_second.term_id),
            repository.confirm_term("owner-b", b_first.term_id),
        )

        assert {confirmed_a_first.layout_slot, confirmed_a_second.layout_slot} == {0, 1}
        assert confirmed_b.layout_slot == 0
        assert {term.term_id for term in await repository.list_terms("owner-a")} == {
            a_first.term_id, a_second.term_id,
        }
        assert [term.term_id for term in await repository.list_terms("owner-b")] == [b_first.term_id]
        with pytest.raises(PersonalTermNotFound):
            await repository.get_term("owner-b", a_first.term_id)

    asyncio.run(database_case(case))
