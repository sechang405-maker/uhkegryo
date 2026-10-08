from __future__ import annotations

import asyncio
import json
import os
import uuid

import asyncpg
import pytest

from backend.db.migrate import migrate
from backend.schemas.enums import ClarificationType, FailureCode, InterpretationState, JobStatus
from backend.schemas.models import InterpretationOutput
from backend.services.agent_worker import AgentJobWorker
from backend.services.catalog_repository import CatalogSnapshot
from backend.services.job_repository import JobRepository, StaleJobAttempt
from backend.services.job_retry_recovery import JobRetryRecovery, retry_delay_ms
from backend.services.llm import LLMInvalidStructuredOutput, LLMRateLimited, LLMTimeout, PromptConfigurationError


@pytest.mark.parametrize(
    ("attempt", "error", "expected_ms"),
    [
        (1, LLMTimeout("timeout"), 1_000),
        (2, LLMTimeout("timeout"), 2_000),
        (1, LLMRateLimited("limited", retry_after_ms=60_000), 30_000),
        (1, LLMRateLimited("limited", retry_after_ms=100), 1_000),
    ],
)
def test_retry_delay_follows_attempt_and_retry_after(attempt, error, expected_ms):
    assert retry_delay_ms(attempt, error) == expected_ms


def test_retry_and_lease_recovery_follow_postgres_contract():
    database_url = os.environ.get("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("TEST_DATABASE_URL is required for the PostgreSQL retry test")

    async def verify_retry_and_recovery():
        schema = f"retry_test_{uuid.uuid4().hex}"
        admin = await asyncpg.connect(database_url)
        pool = None
        try:
            await admin.execute(f'CREATE SCHEMA "{schema}"')

            async def setup_connection(connection):
                await connection.execute(f'SET search_path TO "{schema}"')

            pool = await asyncpg.create_pool(
                database_url, min_size=2, max_size=2, setup=setup_connection
            )
            async with pool.acquire() as connection:
                await migrate(connection)
                session_id = str(uuid.uuid4())
                await connection.execute(
                    """WITH owner AS (INSERT INTO anonymous_owners(owner_id, session_token_hash)
                       VALUES ($1::uuid, $2) RETURNING owner_id)
                       INSERT INTO sessions(session_id, owner_id) SELECT owner_id,owner_id FROM owner""",
                    session_id,
                    uuid.uuid4().hex,
                )

            repository = JobRepository(pool)
            recovery = JobRetryRecovery(pool)
            retry_job, _ = await repository.submit(
                session_id=session_id, request_text="retry", idempotency_key=str(uuid.uuid4())
            )
            claimed = await repository.claim_next()
            assert str(claimed["job_id"]) == retry_job.job_id
            assert claimed["attempt"] == 1

            assert await recovery.handle_attempt_failure(
                job_id=retry_job.job_id,
                attempt=1,
                max_attempts=3,
                error=LLMTimeout("timeout"),
            ) is True
            async with pool.acquire() as connection:
                row = await connection.fetchrow(
                    """SELECT status, attempt, next_retry_at, lease_expires_at, updated_at
                       FROM jobs WHERE job_id=$1::uuid""",
                    retry_job.job_id,
                )
                delay_ms = (row["next_retry_at"] - row["updated_at"]).total_seconds() * 1000
            assert row["status"] == "queued" and row["attempt"] == 1
            assert 800 <= delay_ms <= 1_500
            assert row["lease_expires_at"] is None
            async with pool.acquire() as connection:
                await connection.execute(
                    "UPDATE jobs SET next_retry_at=now()-interval '1 second' WHERE job_id=$1::uuid",
                    retry_job.job_id,
                )
            claimed = await repository.claim_next()
            assert claimed["attempt"] == 2
            assert await recovery.handle_attempt_failure(
                job_id=retry_job.job_id,
                attempt=2,
                max_attempts=3,
                error=LLMRateLimited("limited", retry_after_ms=60_000),
            ) is True
            async with pool.acquire() as connection:
                row = await connection.fetchrow(
                    "SELECT next_retry_at, updated_at FROM jobs WHERE job_id=$1::uuid",
                    retry_job.job_id,
                )
                delay_ms = (row["next_retry_at"] - row["updated_at"]).total_seconds() * 1000
            assert 29_000 <= delay_ms <= 31_000
            assert await repository.claim_next() is None

            async with pool.acquire() as connection:
                await connection.execute(
                    "UPDATE jobs SET next_retry_at=now()-interval '1 second' WHERE job_id=$1::uuid",
                    retry_job.job_id,
                )
            claimed = await repository.claim_next()
            assert claimed["attempt"] == 3
            assert await recovery.handle_attempt_failure(
                job_id=retry_job.job_id,
                attempt=3,
                max_attempts=3,
                error=LLMTimeout("timeout"),
            ) is True
            async with pool.acquire() as connection:
                row = await connection.fetchrow(
                    "SELECT status, succeeded, final_payload_json FROM jobs WHERE job_id=$1::uuid",
                    retry_job.job_id,
                )
            payload = json.loads(row["final_payload_json"])
            assert row["status"] == "failed" and row["succeeded"] is False
            assert payload["failure_code"] == FailureCode.LLM_TIMEOUT.value
            assert await repository.claim_next() is None

            feedback = [{"path": [], "code": "role_duplicate"}]
            feedback_job, _ = await repository.submit(
                session_id=session_id, request_text="feedback", idempotency_key=str(uuid.uuid4())
            )
            await repository.claim_next()
            invalid = LLMInvalidStructuredOutput("invalid", feedback=feedback)
            assert await recovery.handle_attempt_failure(
                job_id=feedback_job.job_id, attempt=1, max_attempts=3, error=invalid
            )
            async with pool.acquire() as connection:
                await connection.execute(
                    "UPDATE jobs SET next_retry_at=now()-interval '1 second' WHERE job_id=$1::uuid",
                    feedback_job.job_id,
                )
            claimed = await repository.claim_next()
            assert json.loads(claimed["validation_feedback_json"]) == feedback
            assert not await recovery.handle_attempt_failure(
                job_id=feedback_job.job_id, attempt=1, max_attempts=3, error=invalid
            )
            async with pool.acquire() as connection:
                saved = await connection.fetchval("SELECT validation_feedback_json FROM jobs WHERE job_id=$1::uuid", feedback_job.job_id)
            assert json.loads(saved) == feedback
            assert await recovery.handle_attempt_failure(
                job_id=feedback_job.job_id, attempt=2, max_attempts=3, error=LLMTimeout("timeout")
            )
            async with pool.acquire() as connection:
                saved = await connection.fetchval("SELECT validation_feedback_json FROM jobs WHERE job_id=$1::uuid", feedback_job.job_id)
            assert saved is None
            async with pool.acquire() as connection:
                await connection.execute("UPDATE jobs SET next_retry_at=now()-interval '1 second' WHERE job_id=$1::uuid", feedback_job.job_id)
            await repository.claim_next()
            assert await recovery.handle_attempt_failure(
                job_id=feedback_job.job_id, attempt=3, max_attempts=3, error=invalid
            )
            async with pool.acquire() as connection:
                row = await connection.fetchrow(
                    "SELECT status, validation_feedback_json, validation_failure_history_json FROM jobs WHERE job_id=$1::uuid",
                    feedback_job.job_id,
                )
            diagnostics = [{"stage": "interpretation_schema", "path": [], "code": "role_duplicate"}]
            assert row["status"] == "failed"
            assert json.loads(row["validation_feedback_json"]) == diagnostics
            assert json.loads(row["validation_failure_history_json"])["3"] == diagnostics

            config_job, _ = await repository.submit(
                session_id=session_id, request_text="configuration", idempotency_key=str(uuid.uuid4())
            )
            claimed = await repository.claim_next()
            assert str(claimed["job_id"]) == config_job.job_id
            assert await recovery.handle_attempt_failure(
                job_id=config_job.job_id,
                attempt=1,
                max_attempts=3,
                error=PromptConfigurationError("missing prompt"),
            ) is True
            async with pool.acquire() as connection:
                row = await connection.fetchrow(
                    "SELECT status, final_payload_json FROM jobs WHERE job_id=$1::uuid",
                    config_job.job_id,
                )
            payload = json.loads(row["final_payload_json"])
            assert row["status"] == "failed"
            assert payload["failure_code"] == FailureCode.CONFIGURATION_ERROR.value

            lease_job, _ = await repository.submit(
                session_id=session_id, request_text="lease", idempotency_key=str(uuid.uuid4())
            )
            claimed = await repository.claim_next()
            assert str(claimed["job_id"]) == lease_job.job_id
            async with pool.acquire() as connection:
                await connection.execute(
                    "UPDATE jobs SET lease_expires_at=now()-interval '1 second' WHERE job_id=$1::uuid",
                    lease_job.job_id,
                )
            assert await recovery.recover_expired_leases() == {"requeued": 1, "failed": 0}
            claimed = await repository.claim_next()
            assert claimed["attempt"] == 2
            with pytest.raises(StaleJobAttempt):
                await repository.update_status(
                    job_id=lease_job.job_id,
                    status=JobStatus.VALIDATING,
                    attempt=1,
                )
            async with pool.acquire() as connection:
                row = await connection.fetchrow(
                    "SELECT status, attempt FROM jobs WHERE job_id=$1::uuid",
                    lease_job.job_id,
                )
            assert row["status"] == "running" and row["attempt"] == 2

            async with pool.acquire() as connection:
                await connection.execute(
                    """UPDATE jobs SET attempt=3, lease_expires_at=now()-interval '1 second'
                       WHERE job_id=$1::uuid""",
                    lease_job.job_id,
                )
            assert await recovery.recover_expired_leases() == {"requeued": 0, "failed": 1}
            async with pool.acquire() as connection:
                row = await connection.fetchrow(
                    "SELECT status, final_payload_json FROM jobs WHERE job_id=$1::uuid",
                    lease_job.job_id,
                )
            payload = json.loads(row["final_payload_json"])
            assert row["status"] == "failed"
            assert payload["failure_code"] == FailureCode.JOB_INSTANCE_INTERRUPTED.value

            heartbeat_job, _ = await repository.submit(
                session_id=session_id, request_text="heartbeat", idempotency_key=str(uuid.uuid4())
            )
            async with pool.acquire() as connection:
                await connection.execute(
                    "UPDATE jobs SET validation_feedback_json=$2::jsonb WHERE job_id=$1::uuid",
                    heartbeat_job.job_id, json.dumps(feedback),
                )
            started = asyncio.Event()
            release = asyncio.Event()

            class SlowAdapter:
                async def memory(self, *args, **kwargs):
                    from backend.schemas.memory import RecallQuery
                    return RecallQuery(mode="none")

                async def interpret(self, request_text, **kwargs):
                    assert kwargs["validation_feedback"] == feedback
                    started.set()
                    await release.wait()
                    return InterpretationOutput(
                        interpretation_state=InterpretationState.NEEDS_CLARIFICATION,
                        unresolved_constraints=["세부 정보"],
                        clarifying_question="어떤 세부 정보인가요?",
                        clarification_type=ClarificationType.ABSTRACT_INTENT,
                    )

            worker = AgentJobWorker(
                pool, CatalogSnapshot(dataset_version="test"),
                adapter=SlowAdapter(), heartbeat_interval=0.01,
            )
            running = asyncio.create_task(worker.run_once())
            await asyncio.wait_for(started.wait(), timeout=2)
            async with pool.acquire() as connection:
                await connection.execute(
                    "UPDATE jobs SET lease_expires_at=now()-interval '1 second' WHERE job_id=$1::uuid",
                    heartbeat_job.job_id,
                )
            async with pool.acquire() as connection:
                for _ in range(200):
                    lease = await connection.fetchval(
                        "SELECT lease_expires_at FROM jobs WHERE job_id=$1::uuid",
                        heartbeat_job.job_id,
                    )
                    if lease > await connection.fetchval("SELECT now() + interval '20 seconds'"):
                        break
                    await asyncio.sleep(0.01)
                else:
                    pytest.fail("heartbeat did not extend the active lease")
            assert await recovery.recover_expired_leases() == {"requeued": 0, "failed": 0}
            release.set()
            await asyncio.wait_for(running, timeout=2)
            async with pool.acquire() as connection:
                row = await connection.fetchrow(
                    "SELECT status, attempt, lease_expires_at, validation_feedback_json FROM jobs WHERE job_id=$1::uuid",
                    heartbeat_job.job_id,
                )
            assert row["status"] == "completed" and row["attempt"] == 1
            assert row["lease_expires_at"] is None
            assert row["validation_feedback_json"] is None
        finally:
            if pool is not None:
                await pool.close()
            await admin.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
            await admin.close()

    asyncio.run(verify_retry_and_recovery())
