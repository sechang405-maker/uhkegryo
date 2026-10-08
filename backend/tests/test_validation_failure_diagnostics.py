import asyncio
import json
import pytest

from backend.services.job_retry_recovery import JobRetryRecovery
from backend.services.llm import LLMInvalidStructuredOutput, LLMTimeout


class Connection:
    async def fetchrow(self, sql, *args):
        self.sql, self.args = sql, args
        return {"job_id": "test"}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


class Pool:
    def __init__(self):
        self.connection = Connection()

    def acquire(self):
        return self.connection


def persisted(error, attempt=3):
    pool = Pool()
    asyncio.run(JobRetryRecovery(pool).handle_attempt_failure(
        job_id="test", attempt=attempt, max_attempts=3, error=error))
    return pool.connection


def test_final_validation_failure_retains_diagnostics():
    connection = persisted(LLMInvalidStructuredOutput("private output", feedback=[
        {"path": ["selections", 0, "evidence"], "code": "missing"}]))
    assert "validation_feedback_json = $6::jsonb" in connection.sql
    assert json.loads(connection.args[5]) == [{
        "stage": "interpretation_schema", "path": ["selections", 0, "evidence"], "code": "missing"}]
    assert "private output" not in repr(connection.args)


def test_final_nonvalidation_failure_clears_diagnostics():
    connection = persisted(LLMTimeout("private timeout"))
    assert "validation_feedback_json = $6::jsonb" in connection.sql
    assert connection.args[5] is None


def test_final_diagnostics_reject_arbitrary_values():
    connection = persisted(LLMInvalidStructuredOutput("secret", feedback=[
        {"path": ["secret", 0], "code": "secret", "input": "secret"}]))
    assert "secret" not in connection.args[5]
    assert json.loads(connection.args[5])[0]["code"] == "invalid_candidate"


def test_retry_feedback_remains_unchanged():
    feedback = [{"path": [], "code": "role_duplicate"}]
    connection = persisted(LLMInvalidStructuredOutput("private", feedback=feedback), attempt=1)
    assert json.loads(connection.args[5]) == feedback


@pytest.mark.parametrize("attempt", [1, 2, 3])
def test_history_stores_safe_diagnostics_for_each_attempt(attempt):
    connection = persisted(LLMInvalidStructuredOutput("private", stage="conversation_validation",
        feedback=[{"path": ["secret", 0, "evidence"], "code": "selection_evidence_invalid",
                   "input": "secret"}]), attempt=attempt)
    assert "validation_failure_history_json = CASE WHEN $7::jsonb IS NULL" in connection.sql
    assert "jsonb_build_object(($2::int)::text, $7::jsonb)" in connection.sql
    assert connection.args[1] == attempt
    assert json.loads(connection.args[6]) == [{"stage": "conversation_validation",
        "path": ["unknown_field", 0, "evidence"], "code": "selection_evidence_invalid"}]


def test_nonvalidation_failure_does_not_add_history():
    assert persisted(LLMTimeout("private"), attempt=1).args[6] is None
    assert persisted(LLMTimeout("private"), attempt=3).args[6] is None


def test_evidence_mismatch_has_specific_diagnostic_stage():
    from backend.schemas.models import InterpretationOutput
    from backend.services.conversation_context import validate

    interpretation = InterpretationOutput(interpretation_state="select_terms", selections=[{
        "role": "body", "term_id": "body_slim", "evidence": ["원문에 없는 표현"], "confidence": 1}])
    with pytest.raises(LLMInvalidStructuredOutput) as raised:
        asyncio.run(validate(None, {"request_text": "마른 캐릭터"}, interpretation, None))
    connection = persisted(raised.value)
    assert json.loads(connection.args[5]) == [{
        "stage": "conversation_validation", "path": [], "code": "selection_evidence_invalid"}]


@pytest.mark.parametrize("stage", ["interpretation_schema", "memory_schema", "conversation_validation"])
def test_preserves_known_stages(stage):
    connection = persisted(LLMInvalidStructuredOutput("private", stage=stage))
    assert json.loads(connection.args[5])[0]["stage"] == stage


def test_attempt_history_survives_postgres_transitions():
    import os
    import uuid
    import asyncpg
    from backend.db.migrate import migrate
    from backend.services.job_repository import JobRepository
    from backend.schemas.models import AgentResult
    from backend.schemas.enums import AgentStatus, JobStatus, ReasonCode

    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL is required")

    async def verify():
        connection = await asyncpg.connect(url)
        schema = "diagnostics_" + uuid.uuid4().hex
        try:
            await connection.execute(f'CREATE SCHEMA "{schema}"')
            await connection.execute(f'SET search_path TO "{schema}"')
            await migrate(connection)
            owner = uuid.uuid4()
            await connection.execute("INSERT INTO anonymous_owners(owner_id, session_token_hash) VALUES ($1,$2)",
                                     owner, uuid.uuid4().hex)
            await connection.execute("INSERT INTO sessions(session_id,owner_id) VALUES ($1,$1)", owner)
            class SinglePool:
                def __getattr__(self, name):
                    return getattr(connection, name)

                def acquire(self):
                    class Lease:
                        async def __aenter__(self):
                            return connection
                        async def __aexit__(self, *args):
                            pass
                    return Lease()

            repository = JobRepository(SinglePool())
            job, _ = await repository.submit(session_id=str(owner), request_text="자세",
                                              idempotency_key=str(uuid.uuid4()))
            await repository.claim_next()
            recovery = JobRetryRecovery(SinglePool())
            async def history():
                return json.loads(await connection.fetchval(
                    "SELECT validation_failure_history_json FROM jobs WHERE job_id=$1::uuid", job.job_id))
            async def retry():
                await connection.execute("UPDATE jobs SET next_retry_at=now() WHERE job_id=$1::uuid", job.job_id)
                await repository.claim_next()

            error = LLMInvalidStructuredOutput("private", stage="conversation_validation",
                feedback=[{"path": [], "code": "selection_evidence_invalid"}])
            assert await recovery.handle_attempt_failure(job_id=job.job_id, attempt=1, max_attempts=3, error=error)
            first = await history()
            await retry()
            assert not await recovery.handle_attempt_failure(job_id=job.job_id, attempt=1, max_attempts=3,
                error=LLMInvalidStructuredOutput("stale", feedback=[{"path": [], "code": "missing"}]))
            assert await history() == first
            assert await recovery.handle_attempt_failure(job_id=job.job_id, attempt=2, max_attempts=3, error=error)
            assert set(await history()) == {"1", "2"}
            await retry()
            await repository.update_status(job_id=job.job_id, attempt=3, status=JobStatus.VALIDATING)
            await repository.update_status(job_id=job.job_id, attempt=3, status=JobStatus.SEARCHING)
            await repository.update_status(job_id=job.job_id, attempt=3, status=JobStatus.RENDERING)
            await repository.update_status(job_id=job.job_id, attempt=3, status=JobStatus.COMPLETED,
                result=AgentResult(agent_status=AgentStatus.NEEDS_CLARIFICATION,
                                   reason_codes=[ReasonCode.INSUFFICIENT_VISUAL_EVIDENCE],
                                   clarifying_question="어떤 자세인가요?"))
            assert set(await history()) == {"1", "2"}
            assert (await history())["1"] == json.loads(connection_safe_diagnostics(error))
            assert await connection.fetchval("SELECT validation_feedback_json FROM jobs WHERE job_id=$1::uuid", job.job_id) is None
            job, _ = await repository.submit(session_id=str(owner), request_text="자세",
                                              idempotency_key=str(uuid.uuid4()))
            await repository.claim_next()
            await recovery.handle_attempt_failure(job_id=job.job_id, attempt=1, max_attempts=3, error=error)
            await retry()
            first = await history()
            await connection.execute("UPDATE jobs SET lease_expires_at=now()-interval '1 second' WHERE job_id=$1::uuid", job.job_id)
            await recovery.recover_expired_leases()
            assert await history() == first
            await retry()
            await recovery.handle_attempt_failure(job_id=job.job_id, attempt=3, max_attempts=3,
                                                 error=LLMTimeout("private timeout"))
            assert await history() == first
        finally:
            await connection.execute(f'DROP SCHEMA "{schema}" CASCADE')
            await connection.close()

    from backend.services.job_retry_recovery import validation_diagnostics as connection_safe_diagnostics
    asyncio.run(verify())
