from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException


def _request(*, role="admin", headers=None):
    return SimpleNamespace(
        state=SimpleNamespace(account=SimpleNamespace(
            account_id="00000000-0000-0000-0000-000000000001",
            role=role,
            status="active",
        )),
        headers=headers or {},
        base_url="http://testserver/",
    )


def test_usage_contract_distinguishes_limit_charged_reserved_and_remaining(monkeypatch):
    from backend.routes import admin_demo
    from backend.schemas.demo_accounts import AccountUsage

    class Quota:
        async def usage(self, account_id):
            assert account_id.endswith("1")
            return AccountUsage(
                unlimited=False, limit=12, charged=7, reserved=2, remaining=3,
            )

    async def services():
        return SimpleNamespace(), SimpleNamespace(), Quota()

    monkeypatch.setattr(admin_demo, "get_admin_services", services)
    response = asyncio.run(admin_demo.account_usage(_request(role="user")))
    assert response.model_dump() == {
        "unlimited": False,
        "limit": 12,
        "charged": 7,
        "reserved": 2,
        "remaining": 3,
    }


def test_usage_contract_represents_unlimited_without_a_fake_large_number(monkeypatch):
    from backend.routes import admin_demo
    from backend.schemas.demo_accounts import AccountUsage

    class Quota:
        async def usage(self, account_id):
            return AccountUsage(
                unlimited=True, limit=None, charged=23, reserved=1, remaining=None,
            )

    async def services():
        return SimpleNamespace(), SimpleNamespace(), Quota()

    monkeypatch.setattr(admin_demo, "get_admin_services", services)
    response = asyncio.run(admin_demo.account_usage(_request(role="admin")))
    assert response.model_dump() == {
        "unlimited": True,
        "limit": None,
        "charged": 23,
        "reserved": 1,
        "remaining": None,
    }


def test_admin_endpoints_reject_non_admin_and_missing_csrf(monkeypatch):
    from backend.routes import admin_demo

    async def services():
        raise AssertionError("authorization must happen before repository access")

    monkeypatch.setattr(admin_demo, "get_admin_services", services)
    with pytest.raises(HTTPException) as denied:
        asyncio.run(admin_demo.admin_overview(_request(role="user")))
    assert denied.value.status_code == 403

    payload = admin_demo.InviteIssueRequest(
        beneficiary_label="tester-1", admin_note="drawing beginner", initial_limit=10,
    )
    with pytest.raises(HTTPException) as csrf:
        asyncio.run(admin_demo.issue_invite(payload, _request()))
    assert csrf.value.status_code == 403


def test_invite_issue_returns_raw_code_once(monkeypatch):
    from backend.routes import admin_demo
    from backend.schemas.demo_accounts import InviteRecord

    record = InviteRecord(
        invite_id="00000000-0000-0000-0000-000000000010",
        beneficiary_label="tester-1",
        admin_note="drawing beginner",
        code_hint="abc123",
        initial_ai_request_limit=10,
        status="pending",
        created_by_account_id="00000000-0000-0000-0000-000000000001",
        created_at="2026-10-26T00:00:00Z",
    )

    class Invites:
        async def issue(self, actor, **values):
            assert values["admin_note"] == "drawing beginner"
            return SimpleNamespace(raw_code="one-time-secret", record=record)

    async def services():
        return SimpleNamespace(), Invites(), SimpleNamespace()

    monkeypatch.setattr(admin_demo, "get_admin_services", services)
    request = _request(headers={"x-admin-action": "issue-invite", "origin": "http://testserver"})
    response = asyncio.run(admin_demo.issue_invite(admin_demo.InviteIssueRequest(
        beneficiary_label="tester-1", admin_note="drawing beginner", initial_limit=10,
    ), request))
    assert response.raw_code == "one-time-secret"
    assert "raw_code" not in response.invite.model_dump()


def test_transfer_approval_requires_admin_action_and_uses_verified_request(monkeypatch):
    from backend.routes import admin_demo

    class Invites:
        async def approve_identity_transfer(self, actor, transfer_id, *, reason):
            assert actor.endswith("1")
            assert transfer_id == "00000000-0000-0000-0000-000000000099"
            assert reason == "verified by operator"

    async def services():
        return SimpleNamespace(), Invites(), SimpleNamespace()

    monkeypatch.setattr(admin_demo, "get_admin_services", services)
    payload = admin_demo.ReasonRequest(reason="verified by operator")
    with pytest.raises(HTTPException) as denied:
        asyncio.run(admin_demo.approve_identity_transfer("00000000-0000-0000-0000-000000000099", payload, _request(role="user")))
    assert denied.value.status_code == 403

    response = asyncio.run(admin_demo.approve_identity_transfer(
        "00000000-0000-0000-0000-000000000099",
        payload,
        _request(headers={"x-admin-action": "approve-transfer", "origin": "http://testserver"}),
    ))
    assert response.status_code == 204
