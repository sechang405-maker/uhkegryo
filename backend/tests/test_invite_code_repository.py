from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from backend.services.invite_code_repository import (
    InviteCodeInvalid,
    InviteCodeRepository,
    InviteRateLimited,
    InviteCodeUnavailable,
    TransferUnavailable,
)
from backend.services.demo_account_repository import AdminPermissionDenied
from backend.services.auth_session_repository import AuthSessionRepository
from backend.tests.test_conversation_sessions import database_case


async def _admin(pool):
    account_id = uuid.uuid4()
    await pool.execute(
        """INSERT INTO accounts(account_id,google_subject,email_normalized,role)
           VALUES($1,$2,$3,'admin')""",
        account_id, f"admin-{account_id}", f"{account_id.hex}@example.com",
    )
    return str(account_id)


def test_code_is_one_time_hashed_and_concurrent_redemption_has_one_account():
    async def case(pool):
        admin = await _admin(pool)
        repo = InviteCodeRepository(pool, pepper="test-pepper")
        issued = await repo.issue(admin, beneficiary_label="초대 사용자 A", initial_limit=7)
        assert issued.raw_code not in str(await pool.fetchrow("SELECT * FROM invites"))
        assert issued.record.code_hint in issued.raw_code

        outcomes = await asyncio.gather(
            repo.redeem(issued.raw_code, google_subject="google-a", verified_email="a@example.com"),
            repo.redeem(issued.raw_code, google_subject="google-b", verified_email="b@example.com"),
            return_exceptions=True,
        )
        accounts = [item for item in outcomes if not isinstance(item, Exception)]
        failures = [item for item in outcomes if isinstance(item, Exception)]
        assert len(accounts) == 1
        assert len(failures) == 1 and isinstance(failures[0], InviteCodeUnavailable)
        assert accounts[0].ai_request_limit == 7
        repeated = await repo.redeem(
            issued.raw_code,
            google_subject=accounts[0].google_subject,
            verified_email=accounts[0].email_normalized,
        )
        assert repeated.account_id == accounts[0].account_id
        assert await pool.fetchval("SELECT count(*) FROM accounts WHERE role='user'") == 1

    asyncio.run(database_case(case))


def test_different_codes_cannot_create_two_accounts_for_the_same_google_identity():
    async def case(pool):
        admin = await _admin(pool)
        repo = InviteCodeRepository(pool, pepper="test-pepper")
        first = await repo.issue(admin, beneficiary_label="same person A", initial_limit=3)
        second = await repo.issue(admin, beneficiary_label="same person B", initial_limit=8)

        outcomes = await asyncio.gather(
            repo.redeem(first.raw_code, google_subject="google-same", verified_email="same@example.com"),
            repo.redeem(second.raw_code, google_subject="google-same", verified_email="same@example.com"),
            return_exceptions=True,
        )
        accounts = [item for item in outcomes if not isinstance(item, Exception)]
        failures = [item for item in outcomes if isinstance(item, Exception)]
        assert len(accounts) == 1
        assert len(failures) == 1 and isinstance(failures[0], InviteCodeUnavailable)
        assert await pool.fetchval("SELECT count(*) FROM accounts WHERE google_subject='google-same'") == 1
        assert await pool.fetchval("SELECT count(*) FROM invites WHERE status='redeemed'") == 1

    asyncio.run(database_case(case))


def test_revoked_expired_and_invalid_codes_do_not_create_accounts():
    async def case(pool):
        admin = await _admin(pool)
        repo = InviteCodeRepository(pool, pepper="test-pepper")
        revoked = await repo.issue(admin, beneficiary_label="revoked")
        await repo.revoke(admin, revoked.record.invite_id, reason="not attending")
        with pytest.raises(InviteCodeUnavailable):
            await repo.redeem(revoked.raw_code, google_subject="revoked", verified_email="r@example.com")

        expired = await repo.issue(
            admin, beneficiary_label="expired",
            expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
        )
        with pytest.raises(InviteCodeUnavailable):
            await repo.redeem(expired.raw_code, google_subject="expired", verified_email="e@example.com")
        with pytest.raises(InviteCodeInvalid):
            await repo.redeem("not-a-real-code", google_subject="invalid", verified_email="i@example.com")
        assert await pool.fetchval("SELECT count(*) FROM accounts WHERE role='user'") == 0

    asyncio.run(database_case(case))


def test_redemption_attempts_are_rate_limited_without_storing_scope_or_code():
    async def case(pool):
        admin = await _admin(pool)
        repo = InviteCodeRepository(pool, pepper="test-pepper", attempt_limit=2)
        issued = await repo.issue(admin, beneficiary_label="rate limited")
        for _ in range(2):
            with pytest.raises(InviteCodeInvalid):
                await repo.redeem(
                    "x" * 24, google_subject="google-rate", verified_email="rate@example.com",
                    attempt_scope="google-rate:127.0.0.1",
                )
        with pytest.raises(InviteRateLimited):
            await repo.redeem(
                issued.raw_code, google_subject="google-rate", verified_email="rate@example.com",
                attempt_scope="google-rate:127.0.0.1",
            )
        stored = str(await pool.fetch("SELECT * FROM invite_redemption_attempts"))
        assert "google-rate" not in stored and "127.0.0.1" not in stored
        assert issued.raw_code not in stored

    asyncio.run(database_case(case))


def test_admin_approved_identity_transfer_preserves_owner_and_quota_and_revokes_sessions():
    async def case(pool):
        admin = await _admin(pool)
        repo = InviteCodeRepository(pool, pepper="test-pepper")
        issued = await repo.issue(admin, beneficiary_label="transfer", initial_limit=4)
        account = await repo.redeem(
            issued.raw_code, google_subject="google-old", verified_email="old@example.com"
        )
        owner_before = await pool.fetchval(
            "SELECT owner_id FROM anonymous_owners WHERE account_id=$1", uuid.UUID(account.account_id)
        )
        await pool.execute(
            """INSERT INTO auth_sessions(auth_session_id,session_token_hash,account_id,expires_at)
               VALUES($1,'old-session',$2,now()+interval '1 hour')""",
            uuid.uuid4(), uuid.UUID(account.account_id),
        )
        registration_token = await AuthSessionRepository(pool).create_registration_session(
            google_subject="google-new",
            verified_email="new@example.com",
            display_name="New identity",
        )
        request = await repo.request_identity_transfer(
            account.account_id, target_registration_token=registration_token,
        )
        with pytest.raises(AdminPermissionDenied):
            await repo.approve_identity_transfer(account.account_id, request.transfer_id)
        transferred = await repo.approve_identity_transfer(admin, request.transfer_id)
        assert transferred.account_id == account.account_id
        assert transferred.google_subject == "google-new"
        assert transferred.ai_request_limit == 4
        assert await pool.fetchval(
            "SELECT owner_id FROM anonymous_owners WHERE account_id=$1", uuid.UUID(account.account_id)
        ) == owner_before
        assert await pool.fetchval(
            "SELECT status FROM auth_sessions WHERE account_id=$1", uuid.UUID(account.account_id)
        ) == "revoked"

    asyncio.run(database_case(case))


def test_identity_transfer_requires_a_live_oidc_verified_registration_session():
    async def case(pool):
        admin = await _admin(pool)
        repo = InviteCodeRepository(pool, pepper="test-pepper")
        issued = await repo.issue(admin, beneficiary_label="transfer source")
        account = await repo.redeem(
            issued.raw_code, google_subject="google-old", verified_email="old@example.com"
        )
        with pytest.raises(TransferUnavailable):
            await repo.request_identity_transfer(
                account.account_id, target_registration_token="unverified-target-identity"
            )

    asyncio.run(database_case(case))


def test_admin_lists_only_verified_pending_transfers_and_can_reject_one():
    async def case(pool):
        admin = await _admin(pool)
        repo = InviteCodeRepository(pool, pepper="test-pepper")
        issued = await repo.issue(admin, beneficiary_label="transfer source", initial_limit=9)
        account = await repo.redeem(
            issued.raw_code, google_subject="google-old", verified_email="old@example.com",
            display_name="Old identity",
        )
        registration_token = await AuthSessionRepository(pool).create_registration_session(
            google_subject="google-target",
            verified_email="target@example.com",
            display_name="Verified target",
        )
        transfer = await repo.request_identity_transfer(
            account.account_id, target_registration_token=registration_token,
        )

        pending = await repo.list_identity_transfers_for_admin(admin)
        assert [item.transfer_id for item in pending] == [transfer.transfer_id]
        assert pending[0].source_account_id == account.account_id
        assert pending[0].target_email == "target@example.com"
        assert pending[0].target_display_name == "Verified target"
        assert not hasattr(pending[0], "target_google_subject")

        rejected = await repo.reject_identity_transfer(admin, transfer.transfer_id, reason="identity mismatch")
        assert rejected.status == "rejected"
        assert await repo.list_identity_transfers_for_admin(admin) == []
        assert await pool.fetchval(
            "SELECT google_subject FROM accounts WHERE account_id=$1", uuid.UUID(account.account_id),
        ) == "google-old"

    asyncio.run(database_case(case))


def test_identity_transfer_request_is_single_pending_and_approval_is_idempotency_safe():
    async def case(pool):
        admin = await _admin(pool)
        repo = InviteCodeRepository(pool, pepper="test-pepper")
        issued = await repo.issue(admin, beneficiary_label="transfer source", initial_limit=5)
        account = await repo.redeem(
            issued.raw_code, google_subject="google-old", verified_email="old@example.com",
        )
        registration_token = await AuthSessionRepository(pool).create_registration_session(
            google_subject="google-target", verified_email="target@example.com", display_name=None,
        )
        first = await repo.request_identity_transfer(
            account.account_id, target_registration_token=registration_token,
        )
        repeated = await repo.request_identity_transfer(
            account.account_id, target_registration_token=registration_token,
        )
        assert repeated.transfer_id == first.transfer_id

        outcomes = await asyncio.gather(
            repo.approve_identity_transfer(admin, first.transfer_id, reason="approved"),
            repo.approve_identity_transfer(admin, first.transfer_id, reason="approved"),
            return_exceptions=True,
        )
        assert len([item for item in outcomes if not isinstance(item, Exception)]) == 1
        assert len([item for item in outcomes if isinstance(item, TransferUnavailable)]) == 1
        assert await pool.fetchval(
            "SELECT ai_request_limit FROM accounts WHERE account_id=$1", uuid.UUID(account.account_id),
        ) == 5
        assert await pool.fetchval(
            "SELECT count(*) FROM anonymous_owners WHERE account_id=$1", uuid.UUID(account.account_id),
        ) == 1

    asyncio.run(database_case(case))
