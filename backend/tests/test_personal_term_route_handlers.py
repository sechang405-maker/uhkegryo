import asyncio
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException, Response

from backend.routes import personal_terms as routes
from backend.schemas.enums import Role
from backend.schemas.personal_terms import PersonalTermRecord, PersonalTermUpdate

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


def record(status="proposed"):
    return PersonalTermRecord(
        personal_term_id=uuid4(), term_id=f"personal_{uuid4().hex}", status=status,
        role=Role.POSE, label_ko="발레 아라베스크", label_en="Ballet arabesque",
        plain_meaning_ko="한쪽 다리로 서서 반대쪽 다리를 뒤로 뻗는 발레 자세입니다.",
        reference_checkpoints_ko=["지지 다리와 척추의 균형을 확인합니다."], cautions_ko=[],
        aliases_ko=["아라베스크"], query_fragments_en=["ballet arabesque pose reference"],
        source_input="발레 동작을 용어로 만들고 싶어", proposal_kind="descriptive",
        uncertainty_ko=None, layout_slot=None, generation_attempts=1,
        created_at="2026-10-23T00:00:00Z", updated_at="2026-10-23T00:00:00Z",
    )


class FakeSessions:
    async def has_owner(self, token): return token == "owner-a"


class FakeRepository:
    def __init__(self): self.item = record()
    async def list_terms(self, token, include_deleted=False): assert token == "owner-a"; return [self.item]
    async def update_term(self, token, term_id, update):
        assert token == "owner-a" and term_id == self.item.term_id
        return self.item.model_copy(update=update.model_dump(exclude_unset=True))
    async def confirm_term(self, token, term_id):
        assert token == "owner-a" and term_id == self.item.term_id
        self.item = self.item.model_copy(update={"status": "active", "layout_slot": 0}); return self.item
    async def soft_delete(self, token, term_id):
        assert token == "owner-a" and term_id == self.item.term_id
        self.item = self.item.model_copy(update={"status": "deleted"}); return self.item
    async def restore_term(self, token, term_id):
        assert token == "owner-a" and term_id == self.item.term_id
        self.item = self.item.model_copy(update={"status": "active"}); return self.item


class FakeGenerator:
    def __init__(self, repository): self.repository, self.calls = repository, []
    async def propose(self, token, source_input, idempotency_key, retry_failed=False):
        self.calls.append((token, source_input, idempotency_key, retry_failed))
        return SimpleNamespace(record=self.repository.item, duplicate_warnings=())


def request(token="owner-a", action=None):
    return SimpleNamespace(cookies={"session_id": token},
        headers={"x-conversation-action": action, "origin": "http://testserver"},
        base_url="http://testserver/", client=SimpleNamespace(host="testclient"),
        app=SimpleNamespace(state=SimpleNamespace()), state=SimpleNamespace())


@pytest.fixture
def services(monkeypatch):
    repository = FakeRepository(); generator = FakeGenerator(repository)
    async def resolve(_request): return FakeSessions(), repository, generator
    async def owner(req, _response, _sessions):
        if req.cookies.get("session_id") != "owner-a":
            raise HTTPException(401, "owner required")
        return "owner-a"
    monkeypatch.setattr(routes, "resolve_services", resolve)
    monkeypatch.setattr(routes, "_owner", owner)
    monkeypatch.setattr(routes, "require_conversation_action", lambda *_args: None)
    return repository, generator


def test_generate_returns_owner_scoped_editable_proposal(services):
    _, generator = services
    result = asyncio.run(routes.generate_proposal(routes.ProposalRequest(
        source_input="발레 동작을 용어로 만들고 싶어"),
        request(action="personal-term-generate"), Response(), "draft-1"))
    assert result.term.status == "proposed"
    assert result.term.plain_meaning_ko.endswith("자세입니다.")
    assert generator.calls == [("owner-a", "발레 동작을 용어로 만들고 싶어", "draft-1", False)]


def test_login_test_mode_rejects_proposal_before_generator_or_quota(services, monkeypatch):
    _, generator = services
    monkeypatch.setattr(
        routes,
        "get_settings",
        lambda: SimpleNamespace(login_test_mode=True),
    )

    with pytest.raises(HTTPException) as raised:
        asyncio.run(routes.generate_proposal(
            routes.ProposalRequest(source_input="발레 포즈를 새 용어로 만들고 싶어"),
            request(action="personal-term-generate"), Response(), "draft-keyless",
        ))

    assert raised.value.status_code == 503
    assert generator.calls == []


def test_google_invite_codex_rejects_non_admin_proposal_before_generator(
    services, monkeypatch,
):
    _, generator = services
    monkeypatch.setattr(
        routes,
        "get_settings",
        lambda: SimpleNamespace(
            login_test_mode=False, llm_backend="codex-cli", auth_mode="google_invite"
        ),
    )
    attempted = request(action="personal-term-generate")
    attempted.state.account = SimpleNamespace(role="user", status="active")

    with pytest.raises(HTTPException) as raised:
        asyncio.run(routes.generate_proposal(
            routes.ProposalRequest(source_input="발레 용어를 하나 만들어줘"),
            attempted, Response(), "draft-admin-only",
        ))

    assert raised.value.status_code == 403
    assert generator.calls == []


def test_edit_then_explicit_confirm_and_list(services):
    repository, _ = services; term_id = repository.item.term_id
    edited = asyncio.run(routes.update_personal_term(term_id,
        PersonalTermUpdate(label_ko="발레 아라베스크 자세"),
        request(action="personal-term-edit"), Response()))
    assert edited.label_ko == "발레 아라베스크 자세"
    assert repository.item.status == "proposed"
    saved = asyncio.run(routes.confirm_personal_term(term_id,
        request(action="personal-term-confirm"), Response()))
    assert saved.status == "active"
    listed = asyncio.run(routes.list_personal_terms(request(), Response()))
    assert listed["items"][0].term_id == term_id


def test_missing_or_other_owner_cookie_is_not_disclosed(services):
    with pytest.raises(HTTPException) as raised:
        asyncio.run(routes.list_personal_terms(request("owner-b"), Response()))
    assert raised.value.status_code == 401


def test_delete_list_deleted_and_restore_are_owner_scoped(services):
    repository, _ = services
    term_id = repository.item.term_id
    deleted = asyncio.run(routes.delete_personal_term(
        term_id, request(action="personal-term-delete"), Response()
    ))
    assert deleted.status == "deleted"
    listed = asyncio.run(routes.list_personal_terms(request(), Response(), include_deleted=True))
    assert listed["items"][0].status == "deleted"
    restored = asyncio.run(routes.restore_personal_term(
        term_id, request(action="personal-term-restore"), Response()
    ))
    assert restored.status == "active"
