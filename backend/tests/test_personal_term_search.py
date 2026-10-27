"""Stage-5 owner-scoped personal term reference search tests."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException, Response

from backend.routes import term_search
from backend.schemas.enums import Role
from backend.schemas.personal_terms import PersonalTermRecord
from backend.services.personal_term_repository import PersonalTermNotFound

@pytest.fixture(autouse=True, scope="module")
def _windows_selector_event_loop_policy():
    """Keep this module's Windows loop workaround from leaking to later tests."""
    if not hasattr(asyncio, "WindowsSelectorEventLoopPolicy"):
        yield
        return

    previous_policy = asyncio.get_event_loop_policy()
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    try:
        yield
    finally:
        asyncio.set_event_loop_policy(previous_policy)


def active_record() -> PersonalTermRecord:
    return PersonalTermRecord(
        personal_term_id=uuid4(), term_id=f"personal_{uuid4().hex}", status="active",
        role=Role.POSE, label_ko="발레 아라베스크", label_en="Ballet arabesque",
        plain_meaning_ko="한쪽 다리로 서서 반대쪽 다리를 뒤로 뻗는 발레 자세입니다.",
        reference_checkpoints_ko=["지지 다리와 척추의 균형"], cautions_ko=[],
        aliases_ko=["아라베스크"], query_fragments_en=["ballet arabesque pose", "full body"],
        source_input="발레 자세", proposal_kind="descriptive", uncertainty_ko=None,
        layout_slot=0, generation_attempts=1,
        created_at="2026-10-23T00:00:00Z", updated_at="2026-10-23T00:00:00Z",
    )


def request(token="owner-a"):
    return SimpleNamespace(cookies={"session_id": token}, app=SimpleNamespace(state=SimpleNamespace()))


def test_personal_search_card_uses_server_owned_active_values(monkeypatch):
    saved = active_record()

    class Sessions:
        _pool = object()

    class Repository:
        def __init__(self, pool): assert pool is Sessions._pool
        async def get_active_term(self, token, term_id):
            assert (token, term_id) == ("owner-a", saved.term_id)
            return saved

    async def repositories(): return Sessions(), object()
    async def owner(_request, _response, _sessions): return "owner-a"
    monkeypatch.setattr(term_search, "get_repositories", repositories)
    monkeypatch.setattr(term_search, "_owner", owner)
    monkeypatch.setattr(term_search, "PersonalTermRepository", Repository)

    card, feedback = asyncio.run(term_search.resolve_personal_search_card(
        request(), Response(), saved.term_id))

    assert card == {
        "role": "pose", "label_ko": saved.label_ko, "label_en": saved.label_en,
        "query_fragments": saved.query_fragments_en, "look_for": saved.reference_checkpoints_ko,
    }
    assert feedback["plain_meaning_ko"] == saved.plain_meaning_ko
    assert feedback["reference_checkpoints_ko"] == saved.reference_checkpoints_ko


def test_personal_search_card_hides_other_owner_or_inactive_term(monkeypatch):
    class Sessions: _pool = object()
    class Repository:
        def __init__(self, _pool): pass
        async def get_active_term(self, _token, _term_id): raise PersonalTermNotFound
    async def repositories(): return Sessions(), object()
    async def owner(_request, _response, _sessions): return "owner-b"
    monkeypatch.setattr(term_search, "get_repositories", repositories)
    monkeypatch.setattr(term_search, "_owner", owner)
    monkeypatch.setattr(term_search, "PersonalTermRepository", Repository)

    with pytest.raises(HTTPException) as raised:
        asyncio.run(term_search.resolve_personal_search_card(
            request("owner-b"), Response(), f"personal_{uuid4().hex}"))
    assert raised.value.status_code == 404


def test_personal_search_card_rejects_missing_saved_search_expression(monkeypatch):
    saved = active_record().model_copy(update={"query_fragments_en": []})
    class Sessions: _pool = object()
    class Repository:
        def __init__(self, _pool): pass
        async def get_active_term(self, _token, _term_id): return saved
    async def repositories(): return Sessions(), object()
    async def owner(_request, _response, _sessions): return "owner-a"
    monkeypatch.setattr(term_search, "get_repositories", repositories)
    monkeypatch.setattr(term_search, "_owner", owner)
    monkeypatch.setattr(term_search, "PersonalTermRepository", Repository)

    with pytest.raises(HTTPException) as raised:
        asyncio.run(term_search.resolve_personal_search_card(
            request(), Response(), saved.term_id))
    assert raised.value.status_code == 409
