from __future__ import annotations

import asyncio
import uuid

import pytest

from backend.services.job_repository import JobRepository, conversation_uses_ai_quota
from backend.services.conversation_memory import ConversationMemory
from backend.services.job_retry_recovery import JobRetryRecovery
from backend.services.quota_repository import QuotaExceeded, QuotaRepository
from backend.schemas.models import AgentResult
from backend.services.session_repository import SessionRepository
from backend.tests.test_conversation_sessions import database_case


async def _account(pool, *, limit: int = 1) -> str:
    account_id = uuid.uuid4()
    await pool.execute(
        """INSERT INTO accounts(account_id,google_subject,email_normalized,ai_request_limit)
           VALUES($1,$2,$3,$4)""",
        account_id,
        f"google-{account_id}",
        f"{account_id.hex}@example.com",
        limit,
    )
    return str(account_id)


def test_only_model_backed_conversations_use_account_quota():
    assert conversation_uses_ai_quota("캐릭터의 역동적인 포즈를 추천해줘") is True
    assert conversation_uses_ai_quota("오늘 저녁 메뉴를 추천해줘") is False
    assert conversation_uses_ai_quota("발레 동작을 새 용어로 추가하고 싶어") is False


def test_job_admission_reserves_once_and_last_unit_is_atomic():
    async def case(pool):
        account_id = await _account(pool, limit=1)
        sessions, jobs = SessionRepository(pool), JobRepository(pool)
        first_session = await sessions.create_session("owner-a")
        second_session = await sessions.create_session("owner-b")
        key = str(uuid.uuid4())

        first, created = await jobs.submit(
            session_id=first_session,
            request_text="역동적인 포즈를 추천해줘",
            idempotency_key=key,
            quota_account_id=account_id,
        )
        repeated, repeated_created = await jobs.submit(
            session_id=first_session,
            request_text="역동적인 포즈를 추천해줘",
            idempotency_key=key,
            quota_account_id=account_id,
        )
        assert created is True and repeated_created is False
        assert repeated.job_id == first.job_id
        assert (await QuotaRepository(pool).usage(account_id)).reserved == 1

        with pytest.raises(QuotaExceeded):
            await jobs.submit(
                session_id=second_session,
                request_text="다른 포즈를 추천해줘",
                idempotency_key=str(uuid.uuid4()),
                quota_account_id=account_id,
            )
        assert await pool.fetchval(
            "SELECT count(*) FROM jobs WHERE session_id=$1", uuid.UUID(second_session)
        ) == 0

    asyncio.run(database_case(case))


def test_free_guidance_creates_no_quota_operation():
    async def case(pool):
        account_id = await _account(pool, limit=0)
        sessions, jobs = SessionRepository(pool), JobRepository(pool)
        session_id = await sessions.create_session("owner-free")
        await jobs.submit(
            session_id=session_id,
            request_text="발레 동작을 새 용어로 추가하고 싶어",
            idempotency_key=str(uuid.uuid4()),
            quota_account_id=account_id,
        )
        assert await pool.fetchval(
            "SELECT count(*) FROM ai_usage_operations WHERE account_id=$1",
            uuid.UUID(account_id),
        ) == 0

    asyncio.run(database_case(case))


def test_conversation_success_charges_and_terminal_failure_releases():
    async def case(pool):
        account_id = await _account(pool, limit=2)
        sessions, jobs = SessionRepository(pool), JobRepository(pool)
        quota = QuotaRepository(pool)
        session_id = await sessions.create_session("owner-terminal")

        completed, _ = await jobs.submit(
            session_id=session_id, request_text="포즈를 추천해줘",
            idempotency_key=str(uuid.uuid4()), quota_account_id=account_id,
        )
        claimed = await jobs.claim_next()
        await pool.execute(
            "UPDATE jobs SET status='rendering' WHERE job_id=$1", uuid.UUID(completed.job_id)
        )
        await ConversationMemory(pool).complete(
            claimed,
            AgentResult(agent_status="drawing_chat", answer_text="자세를 제안합니다."),
            {},
        )
        usage = await quota.usage(account_id)
        assert (usage.charged, usage.reserved, usage.remaining) == (1, 0, 1)

        failed, _ = await jobs.submit(
            session_id=session_id, request_text="다른 포즈를 추천해줘",
            idempotency_key=str(uuid.uuid4()), quota_account_id=account_id,
        )
        failed_claim = await jobs.claim_next()
        assert str(failed_claim["job_id"]) == failed.job_id
        assert await JobRetryRecovery(pool).handle_attempt_failure(
            job_id=failed.job_id, attempt=1, max_attempts=3,
            error=ValueError("terminal test failure"),
        )
        usage = await quota.usage(account_id)
        assert (usage.charged, usage.reserved, usage.remaining) == (1, 0, 1)

    asyncio.run(database_case(case))
