from __future__ import annotations

import asyncio
import uuid

import asyncpg
import pytest

from backend.services.demo_account_repository import (
    AccountConflict,
    AdminPermissionDenied,
    DemoAccountRepository,
    InviteUnavailable,
)
from backend.services.session_repository import SessionRepository
from backend.tests.test_conversation_sessions import database_case


async def _seed_account(pool, *, role="user", status="active", limit=0, email=None):
    account_id = uuid.uuid4()
    email = email or f"{account_id.hex}@example.com"
    await pool.execute(
        """INSERT INTO accounts(
               account_id, google_subject, email_normalized, role, status, ai_request_limit)
           VALUES($1,$2,$3,$4,$5,$6)""",
        account_id, f"google-{account_id}", email, role, status, limit,
    )
    return str(account_id)


def test_invited_account_starts_at_zero_and_preserves_anonymous_owner_data():
    async def case(pool):
        accounts = DemoAccountRepository(pool)
        sessions = SessionRepository(pool)
        legacy_session = await sessions.create_session("legacy-cookie")
        admin_id = await _seed_account(pool, role="admin", email="admin@example.com")

        invitation = await accounts.create_invite(admin_id, "  Person@Example.COM  ")
        assert invitation.email_normalized == "person@example.com"
        repeated = await accounts.create_invite(admin_id, "person@example.com")
        assert repeated.invite_id == invitation.invite_id

        concurrent = await asyncio.gather(*[
            accounts.create_invite(admin_id, "concurrent@example.com") for _ in range(2)
        ])
        assert len({item.invite_id for item in concurrent}) == 1
        assert await pool.fetchval(
            "SELECT count(*) FROM admin_audit_events WHERE action='invite_created'"
        ) == 2

        account = await accounts.accept_invite(
            google_subject="google-person", verified_email="PERSON@example.com",
            display_name="Person",
        )
        assert account.email_normalized == "person@example.com"
        assert account.ai_request_limit == 0
        assert account.status == "active" and account.role == "user"
        assert (await accounts.accept_invite(
            google_subject="google-person", verified_email="person@example.com",
            display_name="Person",
        )).account_id == account.account_id

        owner = await pool.fetchrow(
            "SELECT account_id,session_token_hash FROM anonymous_owners WHERE account_id=$1",
            uuid.UUID(account.account_id),
        )
        assert str(owner["account_id"]) == account.account_id
        assert owner["session_token_hash"] is None
        assert await sessions.resolve_session("legacy-cookie") == legacy_session
        legacy_owner = await pool.fetchrow(
            """SELECT o.owner_id,o.account_id FROM anonymous_owners o
               JOIN sessions s USING(owner_id) WHERE s.session_id=$1""",
            uuid.UUID(legacy_session),
        )
        assert legacy_owner["account_id"] is None
        with pytest.raises(asyncpg.CheckViolationError):
            await pool.execute(
                "UPDATE anonymous_owners SET account_id=$2 WHERE owner_id=$1",
                legacy_owner["owner_id"], uuid.UUID(admin_id),
            )

        accepted_invite = await pool.fetchrow(
            "SELECT status,accepted_by_account_id FROM invites WHERE invite_id=$1",
            uuid.UUID(invitation.invite_id),
        )
        assert accepted_invite["status"] == "accepted"
        assert str(accepted_invite["accepted_by_account_id"]) == account.account_id

        with pytest.raises(InviteUnavailable):
            await accounts.accept_invite(
                google_subject="google-stranger", verified_email="stranger@example.com",
            )
        with pytest.raises(AccountConflict):
            await accounts.accept_invite(
                google_subject="different-subject", verified_email="person@example.com",
            )

    asyncio.run(database_case(case))


def test_only_active_admin_can_invite_disable_and_adjust_limit_with_audit():
    async def case(pool):
        accounts = DemoAccountRepository(pool)
        admin_id = await _seed_account(pool, role="admin", email="admin@example.com")
        user_id = await _seed_account(pool, email="user@example.com")
        target_id = await _seed_account(pool, email="target@example.com")

        with pytest.raises(AdminPermissionDenied):
            await accounts.create_invite(user_id, "blocked@example.com")
        with pytest.raises(AdminPermissionDenied):
            await accounts.set_ai_request_limit(user_id, target_id, 5, reason="not allowed")

        adjusted = await accounts.set_ai_request_limit(
            admin_id, target_id, 7, reason="demo allocation",
        )
        assert adjusted.ai_request_limit == 7
        disabled = await accounts.set_account_status(
            admin_id, target_id, "disabled", reason="demo paused",
        )
        assert disabled.status == "disabled"

        events = await pool.fetch(
            """SELECT action,details_json->>'previous_limit' AS previous_limit,
                      details_json->>'new_limit' AS new_limit,
                      details_json->>'reason' AS reason
               FROM admin_audit_events
               WHERE actor_account_id=$1 AND target_account_id=$2 ORDER BY created_at,event_id""",
            uuid.UUID(admin_id), uuid.UUID(target_id),
        )
        assert [row["action"] for row in events] == ["quota_limit_changed", "account_disabled"]
        assert (events[0]["previous_limit"], events[0]["new_limit"]) == ("0", "7")
        assert events[1]["reason"] == "demo paused"

        await pool.execute("UPDATE accounts SET status='disabled' WHERE account_id=$1", uuid.UUID(admin_id))
        with pytest.raises(AdminPermissionDenied):
            await accounts.set_ai_request_limit(admin_id, target_id, 8, reason="disabled admin")

    asyncio.run(database_case(case))
