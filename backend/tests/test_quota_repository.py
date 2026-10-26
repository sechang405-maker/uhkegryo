from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import asyncpg
import pytest

from backend.services.quota_repository import (
    AccountUnavailable,
    QuotaExceeded,
    QuotaIdempotencyConflict,
    QuotaRepository,
    QuotaStateConflict,
)
from backend.tests.test_conversation_sessions import database_case


async def _seed_account(pool, *, limit=0, status="active"):
    account_id = uuid.uuid4()
    await pool.execute(
        """INSERT INTO accounts(
               account_id, google_subject, email_normalized, status, ai_request_limit)
           VALUES($1,$2,$3,$4,$5)""",
        account_id, f"google-{account_id}", f"{account_id.hex}@example.com", status, limit,
    )
    return str(account_id)


def test_zero_limit_and_concurrent_last_unit_are_enforced_atomically():
    async def case(pool):
        quota = QuotaRepository(pool)
        zero_id = await _seed_account(pool, limit=0)
        with pytest.raises(QuotaExceeded):
            await quota.reserve(zero_id, "conversation", "zero-key", "request-zero")

        account_id = await _seed_account(pool, limit=1)
        outcomes = await asyncio.gather(
            quota.reserve(account_id, "conversation", "key-a", "request-a"),
            quota.reserve(account_id, "conversation", "key-b", "request-b"),
            return_exceptions=True,
        )
        reservations = [value for value in outcomes if not isinstance(value, Exception)]
        failures = [value for value in outcomes if isinstance(value, Exception)]
        assert len(reservations) == 1
        assert len(failures) == 1 and isinstance(failures[0], QuotaExceeded)
        usage = await quota.usage(account_id)
        assert (usage.limit, usage.charged, usage.reserved, usage.remaining) == (1, 0, 1, 0)

    asyncio.run(database_case(case))


def test_reservation_idempotency_is_scoped_by_account_and_payload():
    async def case(pool):
        quota = QuotaRepository(pool)
        first_id = await _seed_account(pool, limit=2)
        second_id = await _seed_account(pool, limit=2)

        first = await quota.reserve(first_id, "conversation", "shared-key", "request-a")
        repeated = await quota.reserve(first_id, "conversation", "shared-key", "request-a")
        other_owner = await quota.reserve(second_id, "conversation", "shared-key", "request-a")
        assert repeated.operation_id == first.operation_id
        assert other_owner.operation_id != first.operation_id

        with pytest.raises(QuotaIdempotencyConflict):
            await quota.reserve(first_id, "conversation", "shared-key", "different-request")
        with pytest.raises(asyncpg.CheckViolationError):
            await pool.execute(
                "UPDATE ai_usage_operations SET finalized_at=now() WHERE operation_id=$1",
                uuid.UUID(first.operation_id),
            )

        charged = await quota.charge(first_id, first.operation_id)
        assert charged.state == "charged"
        assert (await quota.charge(first_id, first.operation_id)).state == "charged"
        with pytest.raises(QuotaStateConflict):
            await quota.release(first_id, first.operation_id, reason="cannot undo success")

        released = await quota.release(second_id, other_owner.operation_id, reason="provider failed")
        assert released.state == "released"
        assert (await quota.release(
            second_id, other_owner.operation_id, reason="duplicate cleanup"
        )).state == "released"
        with pytest.raises(QuotaStateConflict):
            await quota.charge(second_id, other_owner.operation_id)

    asyncio.run(database_case(case))


def test_reserved_work_can_finish_after_limit_reduction_or_account_disable():
    async def case(pool):
        quota = QuotaRepository(pool)
        account_id = await _seed_account(pool, limit=2)
        reserved = await quota.reserve(
            account_id, "personal_term_proposal", "proposal-key", "proposal-input"
        )
        await pool.execute(
            "UPDATE accounts SET ai_request_limit=0,status='disabled' WHERE account_id=$1",
            uuid.UUID(account_id),
        )

        assert (await quota.charge(account_id, reserved.operation_id)).state == "charged"
        usage = await quota.usage(account_id)
        assert (usage.limit, usage.charged, usage.reserved, usage.remaining) == (0, 1, 0, 0)
        with pytest.raises(AccountUnavailable):
            await quota.reserve(account_id, "conversation", "new-key", "new-request")

    asyncio.run(database_case(case))


def test_stale_reservations_require_explicit_recovery_decision():
    async def case(pool):
        quota = QuotaRepository(pool)
        account_id = await _seed_account(pool, limit=3)
        stale = await quota.reserve(account_id, "conversation", "stale", "stale-request")
        recent = await quota.reserve(account_id, "conversation", "recent", "recent-request")
        charged = await quota.reserve(account_id, "conversation", "charged", "charged-request")
        await quota.charge(account_id, charged.operation_id)
        await pool.execute(
            "UPDATE ai_usage_operations SET reserved_at=now()-interval '2 hours' WHERE operation_id=$1",
            uuid.UUID(stale.operation_id),
        )

        candidates = await quota.list_recovery_candidates(
            before=datetime.now(timezone.utc) - timedelta(hours=1), limit=10,
        )
        assert [item.operation_id for item in candidates] == [stale.operation_id]
        assert (await quota.usage(account_id)).reserved == 2
        await quota.release(account_id, stale.operation_id, reason="authoritative job failed")
        assert (await quota.usage(account_id)).reserved == 1
        assert recent.state == "reserved"

    asyncio.run(database_case(case))
