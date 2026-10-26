from __future__ import annotations

import asyncio
import uuid
from datetime import timedelta

import pytest

from backend.services.auth_session_repository import (
    AuthSessionRepository,
    AuthSessionUnavailable,
    OIDCFlowUnavailable,
)
from backend.services.session_repository import SessionRepository
from backend.tests.test_conversation_sessions import database_case


async def _account(pool):
    account_id = uuid.uuid4()
    await pool.execute(
        """INSERT INTO accounts(account_id,google_subject,email_normalized)
           VALUES($1,$2,$3)""",
        account_id, f"google-{account_id}", f"{account_id.hex}@example.com",
    )
    await pool.execute(
        "INSERT INTO anonymous_owners(owner_id,account_id) VALUES($1,$2)", uuid.uuid4(), account_id,
    )
    return str(account_id)


def test_oidc_flow_is_one_time_and_registration_session_cannot_resolve_as_app_session():
    async def case(pool):
        repo = AuthSessionRepository(pool)
        await repo.store_oidc_flow("state", "nonce", "verifier", ttl=timedelta(minutes=5))
        flow = await repo.consume_oidc_flow("state")
        assert (flow.nonce, flow.code_verifier) == ("nonce", "verifier")
        with pytest.raises(OIDCFlowUnavailable):
            await repo.consume_oidc_flow("state")

        token = await repo.create_registration_session(
            google_subject="new-google", verified_email="new@example.com", display_name="New"
        )
        registration = await repo.resolve_registration_session(token)
        assert registration.google_subject == "new-google"
        with pytest.raises(AuthSessionUnavailable):
            await repo.resolve_app_session(token)

    asyncio.run(database_case(case))


def test_app_session_is_hashed_expires_and_revokes():
    async def case(pool):
        account_id = await _account(pool)
        repo = AuthSessionRepository(pool)
        token = await repo.create_app_session(account_id)
        assert token not in str(await pool.fetchrow("SELECT * FROM auth_sessions"))
        resolved = await repo.resolve_app_session(token)
        assert resolved.account_id == account_id
        conversation = await SessionRepository(pool).create_session(token)
        assert await SessionRepository(pool).resolve_session(token) == conversation
        await repo.revoke_app_session(token)
        with pytest.raises(AuthSessionUnavailable):
            await repo.resolve_app_session(token)

    asyncio.run(database_case(case))
