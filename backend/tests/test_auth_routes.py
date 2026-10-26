from __future__ import annotations

import asyncio

import httpx
import pytest

from backend.services.google_oidc import GoogleIdentity
from backend.tests.test_conversation_sessions import database_case


class FakeOIDC:
    async def authorization_url(self):
        return "https://accounts.google.com/o/oauth2/v2/auth?state=fixed"

    async def verify_callback(self, *, state, code):
        assert (state, code) == ("state", "code")
        return GoogleIdentity("google-new", "new@example.com", "New User")


def test_new_google_identity_gets_limited_registration_then_redeems_code(monkeypatch):
    from backend.main import app, settings
    from backend.routes import auth
    from backend.services.auth_session_repository import AuthSessionRepository
    from backend.services.demo_account_repository import DemoAccountRepository
    from backend.services.invite_code_repository import InviteCodeRepository

    async def case(pool):
        previous_mode = settings.auth_mode
        settings.auth_mode = "google_invite"
        accounts = DemoAccountRepository(pool)
        sessions = AuthSessionRepository(pool)
        invites = InviteCodeRepository(pool, pepper="test-pepper")
        admin_id = await pool.fetchval(
            """INSERT INTO accounts(account_id,google_subject,email_normalized,role)
               VALUES(gen_random_uuid(),'admin','admin@example.com','admin') RETURNING account_id"""
        )
        issued = await invites.issue(str(admin_id), beneficiary_label="invited", initial_limit=3)

        async def services():
            return accounts, sessions, invites, FakeOIDC()
        monkeypatch.setattr(auth, "get_auth_services", services)
        monkeypatch.setattr(auth, "auth_frontend_origin", lambda: "http://frontend.test")

        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test",
                follow_redirects=False,
            ) as client:
                start = await client.get("/api/auth/google/start?return_url=https://evil.example")
                assert start.status_code == 307
                assert start.headers["location"].startswith("https://accounts.google.com/")

                callback = await client.get("/api/auth/google/callback?state=state&code=code")
                assert callback.status_code == 307
                assert callback.headers["location"] == "http://frontend.test/invite"
                assert client.cookies.get("registration_session")
                assert client.cookies.get("session_id") is None

                blocked = await client.post("/api/agent", json={"request_text": "test"})
                assert blocked.status_code == 401

                redeemed = await client.post(
                    "/api/auth/invite/redeem", json={"code": issued.raw_code},
                    headers={"origin": "http://test", "x-auth-action": "redeem"},
                )
                assert redeemed.status_code == 200
                assert redeemed.json()["account"]["ai_request_limit"] == 3
                assert client.cookies.get("session_id")
                assert client.cookies.get("registration_session") is None
                me = await client.get("/api/auth/me")
                assert me.json()["state"] == "authenticated"
        finally:
            settings.auth_mode = previous_mode

    asyncio.run(database_case(case))


def test_fail_closed_mode_requires_auth_session_but_local_mode_preserves_health(monkeypatch):
    from backend.main import app, settings

    async def case(pool):
        previous = settings.auth_mode
        settings.auth_mode = "google_invite"
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                assert (await client.get("/health")).status_code == 200
                assert (await client.get("/api/sessions")).status_code == 401
        finally:
            settings.auth_mode = previous

    asyncio.run(database_case(case))


def test_returning_google_identity_logs_in_without_reentering_invite(monkeypatch):
    from backend.main import app, settings
    from backend.routes import auth
    from backend.services.auth_session_repository import AuthSessionRepository
    from backend.services.demo_account_repository import DemoAccountRepository
    from backend.services.invite_code_repository import InviteCodeRepository

    async def case(pool):
        account_id = await pool.fetchval(
            """INSERT INTO accounts(account_id,google_subject,email_normalized)
               VALUES(gen_random_uuid(),'google-new','old@example.com') RETURNING account_id"""
        )
        await pool.execute(
            "INSERT INTO anonymous_owners(owner_id,account_id) VALUES(gen_random_uuid(),$1)",
            account_id,
        )
        accounts = DemoAccountRepository(pool)
        sessions = AuthSessionRepository(pool)

        async def services():
            return accounts, sessions, InviteCodeRepository(pool, pepper="test-pepper"), FakeOIDC()

        monkeypatch.setattr(auth, "get_auth_services", services)
        monkeypatch.setattr(auth, "auth_frontend_origin", lambda: "http://frontend.test")
        previous_mode = settings.auth_mode
        settings.auth_mode = "google_invite"
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test",
                follow_redirects=False,
            ) as client:
                client.cookies.set(
                    "registration_session", "stale-registration", domain="test.local", path="/"
                )
                callback = await client.get("/api/auth/google/callback?state=state&code=code")
                assert callback.headers["location"] == "http://frontend.test/"
                assert client.cookies.get("session_id")
                assert client.cookies.get("registration_session") is None
            row = await pool.fetchrow(
                "SELECT email_normalized,last_login_at FROM accounts WHERE account_id=$1", account_id,
            )
            assert row["email_normalized"] == "new@example.com"
            assert row["last_login_at"] is not None
        finally:
            settings.auth_mode = previous_mode

    asyncio.run(database_case(case))


def test_disabled_account_is_rejected_without_updating_login_metadata(monkeypatch):
    from backend.main import app, settings
    from backend.routes import auth
    from backend.services.auth_session_repository import AuthSessionRepository
    from backend.services.demo_account_repository import DemoAccountRepository
    from backend.services.invite_code_repository import InviteCodeRepository

    async def case(pool):
        account_id = await pool.fetchval(
            """INSERT INTO accounts(account_id,google_subject,email_normalized,status,last_login_at)
               VALUES(gen_random_uuid(),'google-new','old@example.com','disabled',NULL)
               RETURNING account_id"""
        )
        accounts = DemoAccountRepository(pool)
        sessions = AuthSessionRepository(pool)

        async def services():
            return accounts, sessions, InviteCodeRepository(pool, pepper="test-pepper"), FakeOIDC()

        monkeypatch.setattr(auth, "get_auth_services", services)
        monkeypatch.setattr(auth, "auth_frontend_origin", lambda: "http://frontend.test")
        previous_mode = settings.auth_mode
        settings.auth_mode = "google_invite"
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test",
                follow_redirects=False,
            ) as client:
                callback = await client.get("/api/auth/google/callback?state=state&code=code")
                assert callback.status_code == 403
                assert client.cookies.get("session_id") is None
            row = await pool.fetchrow(
                "SELECT email_normalized,last_login_at FROM accounts WHERE account_id=$1", account_id,
            )
            assert row["email_normalized"] == "old@example.com"
            assert row["last_login_at"] is None
        finally:
            settings.auth_mode = previous_mode

    asyncio.run(database_case(case))


def test_signed_in_account_requests_transfer_only_after_second_google_identity_is_verified(monkeypatch):
    from backend.main import app, settings
    from backend.routes import auth
    from backend.services.auth_session_repository import AuthSessionRepository
    from backend.services.demo_account_repository import DemoAccountRepository
    from backend.services.invite_code_repository import InviteCodeRepository

    async def case(pool):
        account_id = await pool.fetchval(
            """INSERT INTO accounts(account_id,google_subject,email_normalized,ai_request_limit)
               VALUES(gen_random_uuid(),'google-old','old@example.com',11) RETURNING account_id"""
        )
        await pool.execute(
            "INSERT INTO anonymous_owners(owner_id,account_id) VALUES(gen_random_uuid(),$1)", account_id,
        )
        accounts = DemoAccountRepository(pool)
        sessions = AuthSessionRepository(pool)
        invites = InviteCodeRepository(pool, pepper="test-pepper")

        async def services():
            return accounts, sessions, invites, FakeOIDC()

        monkeypatch.setattr(auth, "get_auth_services", services)
        monkeypatch.setattr(auth, "auth_frontend_origin", lambda: "http://frontend.test")
        previous_mode = settings.auth_mode
        settings.auth_mode = "google_invite"
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test", follow_redirects=False,
            ) as client:
                app_token = await sessions.create_app_session(str(account_id))
                client.cookies.set("session_id", app_token, domain="test.local", path="/")
                callback = await client.get("/api/auth/google/callback?state=state&code=code")
                assert callback.headers["location"] == "http://frontend.test/transfer"
                assert client.cookies.get("session_id") == app_token
                assert client.cookies.get("registration_session")

                status = await client.get("/api/auth/identity-transfer/status")
                assert status.status_code == 200
                assert status.json()["source_email"] == "old@example.com"
                assert status.json()["target_email"] == "new@example.com"

                assert (await client.post("/api/auth/identity-transfer/request")).status_code == 403
                requested = await client.post(
                    "/api/auth/identity-transfer/request",
                    headers={"origin": "http://test", "x-auth-action": "request-transfer"},
                )
                assert requested.status_code == 200
                assert requested.json()["status"] == "pending"
            assert await pool.fetchval(
                "SELECT count(*) FROM identity_transfer_requests WHERE account_id=$1 AND status='pending'",
                account_id,
            ) == 1
        finally:
            settings.auth_mode = previous_mode

    asyncio.run(database_case(case))
