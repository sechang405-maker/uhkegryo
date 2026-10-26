from __future__ import annotations

import asyncio
import uuid

import pytest

from backend.services.llm import LLMTimeout
from backend.services.personal_term_generator import PersonalTermGenerationFailed, PersonalTermGenerator
from backend.services.personal_term_repository import PersonalTermRepository
from backend.services.quota_repository import QuotaExceeded, QuotaRepository
from backend.shared.auth import hash_session_token
from backend.tests.test_conversation_sessions import database_case
from backend.tests.test_personal_term_generator import RecordingTransport, catalog, generated_payload


async def _authenticated_owner(pool, *, limit: int) -> tuple[str, str]:
    account_id, owner_id, auth_session_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    token = f"auth-{account_id}"
    await pool.execute(
        """INSERT INTO accounts(account_id,google_subject,email_normalized,ai_request_limit)
           VALUES($1,$2,$3,$4)""",
        account_id, f"google-{account_id}", f"{account_id.hex}@example.com", limit,
    )
    await pool.execute(
        "INSERT INTO anonymous_owners(owner_id,account_id) VALUES($1,$2)",
        owner_id, account_id,
    )
    await pool.execute(
        """INSERT INTO auth_sessions(auth_session_id,session_token_hash,account_id,expires_at)
           VALUES($1,$2,$3,now()+interval '1 hour')""",
        auth_session_id, hash_session_token(token), account_id,
    )
    return token, str(account_id)


def test_success_charges_once_and_failure_releases_for_explicit_retry():
    async def case(pool):
        token, account_id = await _authenticated_owner(pool, limit=1)
        repository, quota = PersonalTermRepository(pool), QuotaRepository(pool)
        transport = RecordingTransport(LLMTimeout("timeout"), generated_payload())
        generator = PersonalTermGenerator(
            repository, catalog(), transport=transport, quota=quota,
        )

        with pytest.raises(PersonalTermGenerationFailed):
            await generator.propose(token, "발레 점프", idempotency_key="proposal-1")
        assert (await quota.usage(account_id)).remaining == 1

        result = await generator.propose(
            token, "발레 점프", idempotency_key="proposal-1", retry_failed=True,
        )
        assert result.record.status == "proposed"
        usage = await quota.usage(account_id)
        assert (usage.charged, usage.reserved, usage.remaining) == (1, 0, 0)
        repeated = await generator.propose(token, "발레 점프", idempotency_key="proposal-1")
        assert repeated.record.term_id == result.record.term_id
        assert len(transport.calls) == 2

    asyncio.run(database_case(case))


def test_zero_quota_blocks_transport_and_leaves_retryable_failed_draft():
    async def case(pool):
        token, _ = await _authenticated_owner(pool, limit=0)
        repository, quota = PersonalTermRepository(pool), QuotaRepository(pool)
        transport = RecordingTransport(generated_payload())
        generator = PersonalTermGenerator(
            repository, catalog(), transport=transport, quota=quota,
        )
        with pytest.raises(QuotaExceeded):
            await generator.propose(token, "발레 점프", idempotency_key="proposal-zero")
        assert transport.calls == []
        state = await repository.get_generation(token, "proposal-zero")
        assert state.status == "failed"

    asyncio.run(database_case(case))
