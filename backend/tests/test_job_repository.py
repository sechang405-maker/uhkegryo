from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import json
import os
import uuid

import asyncpg
import pytest

from backend.db.migrate import migrate
from backend.schemas import AgentResult, Failure
from backend.schemas.enums import AgentStatus, FailureCode, JobStatus, ReasonCode
from backend.services.job_repository import (
    IdempotencyConflict,
    InvalidJobTransition,
    JobNotFound,
    JobRepository,
    StaleJobAttempt,
)
from backend.shared.auth import hash_session_token


class FakeConnection:
    def __init__(
        self, rows=(), update_row=True, fail_job_insert=False, status="rendering", attempt=1
    ):
        self.rows = list(rows)
        self.update_row = update_row
        self.fail_job_insert = fail_job_insert
        self.status = status
        self.attempt = attempt
        self.calls = []
        self.rolled_back = False
        self.transaction_count = 0

    async def execute(self, query, *args):
        self.calls.append((query, args))
        return "SELECT 1"

    async def fetchval(self, query, *args):
        self.calls.append((query, args))
        return args[0]

    async def fetchrow(self, query, *args):
        self.calls.append((query, args))
        if "INSERT INTO anonymous_owners" in query:
            return {"owner_id": args[0], "default_session_id": None}
        if "SET lease_expires_at = now()" in query:
            if self.status not in args[2] or self.attempt != args[1]:
                return None
            return {"job_id": args[0]}
        if "UPDATE jobs AS claimed" in query:
            row = _job_row((JOB_ID, SESSION_ID, "draw", "hash", "key", None,
                            "running", 1, 3, None))
            row["lease_expires_at"] = datetime.now(timezone.utc)
            return row
        if query.lstrip().startswith("SELECT * FROM jobs"):
            return self.rows.pop(0) if self.rows else None
        if "INSERT INTO jobs" in query:
            if self.fail_job_insert:
                raise RuntimeError("job insert failed")
            row = _job_row((args[0], args[1], args[2], args[3], args[4], None,
                            args[5], 0, args[6], None))
            return row
        if "UPDATE jobs" in query:
            if not self.update_row or self.status not in args[5] or self.attempt != args[6]:
                return None
            row = _job_row((args[0], SESSION_ID, "text", "hash", "key", None,
                            args[1], 0, 3, None))
            row["attempt"] = args[6]
            row["status"] = args[1]
            row["succeeded"] = args[1] == "completed" if args[1] in ("completed", "failed") else None
            row["final_payload_json"] = args[2] if args[1] == "completed" else args[3] if args[1] == "failed" else None
            return row
        if query.lstrip().startswith("SELECT status, attempt FROM jobs"):
            return {"status": self.status, "attempt": self.attempt} if self.status is not None else None
        raise AssertionError(query)

    @asynccontextmanager
    async def transaction(self):
        self.transaction_count += 1
        try:
            yield
        except BaseException:
            self.rolled_back = True
            raise


class FakePool:
    def __init__(self, connection):
        self.connection = connection

    @asynccontextmanager
    async def acquire(self):
        yield self.connection

    async def fetchrow(self, query, *args):
        return await self.connection.fetchrow(query, *args)


SESSION_ID = "a8098b2a-941e-4ce9-9dd2-22da1b55d744"
JOB_ID = "51498152-d371-4fd8-9e5a-a81befee3b17"


def _job_row(args):
    return {
        "job_id": args[0], "session_id": args[1], "request_text": args[2],
        "request_text_hash": args[3], "idempotency_key_hash": args[4],
        "idempotency_expires_at": datetime.now(timezone.utc), "status": args[6],
        "attempt": args[7], "max_attempts": args[8], "next_retry_at": None,
        "succeeded": None, "final_payload_json": None,
    }


def _run(awaitable):
    return asyncio.run(awaitable)


def test_submit_creates_hashed_queued_job_under_session_lock():
    connection = FakeConnection()
    job, created = _run(JobRepository(FakePool(connection)).submit(
        session_id=SESSION_ID, request_text="draw", idempotency_key=JOB_ID
    ))

    assert created is True
    assert job.job_status is JobStatus.QUEUED and job.attempt == 1
    lock_query, lock_args = connection.calls[0]
    assert "pg_advisory_xact_lock" in lock_query
    assert lock_args == (SESSION_ID,)
    lookup_query, _ = connection.calls[2]
    assert "idempotency_expires_at > now()" in lookup_query
    insert_query, insert_args = connection.calls[3]
    assert "INSERT INTO jobs" in insert_query
    assert insert_args[2] == "draw"
    assert insert_args[3] != "draw"
    assert insert_args[4] != JOB_ID


def test_new_session_and_job_share_transaction():
    connection = FakeConnection()
    token = "opaque-session-token"

    job, created = _run(JobRepository(FakePool(connection)).submit_new_session(
        session_token=token, request_text="draw", idempotency_key=JOB_ID
    ))

    session_query, session_args = connection.calls[0]
    assert "INSERT INTO anonymous_owners" in session_query
    assert session_args[1] == hash_session_token(token)
    assert "opaque-session-token" not in session_args
    insert = next(args for query, args in connection.calls if "INSERT INTO jobs" in query)
    assert insert[1] == job.session_id
    assert created is True
    assert connection.rolled_back is False


def test_new_session_rolls_back_when_job_insert_fails():
    connection = FakeConnection(fail_job_insert=True)

    with pytest.raises(RuntimeError, match="job insert failed"):
        _run(JobRepository(FakePool(connection)).submit_new_session(
            session_token="opaque-session-token",
            request_text="draw",
            idempotency_key=JOB_ID,
        ))

    assert any("INSERT INTO sessions" in query for query, _ in connection.calls)
    assert any("INSERT INTO jobs" in query for query, _ in connection.calls)
    assert connection.rolled_back is True


def test_submit_reuses_matching_unexpired_job():
    existing = _job_row((JOB_ID, SESSION_ID, "draw", "same-hash", "key", None,
                         "queued", 0, 3, None))
    from backend.services.job_repository import _hash
    existing["request_text_hash"] = _hash("draw")
    connection = FakeConnection([existing])

    job, created = _run(JobRepository(FakePool(connection)).submit(
        session_id=SESSION_ID, request_text="draw", idempotency_key=JOB_ID
    ))

    assert job.job_id == JOB_ID and created is False
    assert len(connection.calls) == 3


def test_submit_rejects_same_key_with_different_request_text():
    existing = _job_row((JOB_ID, SESSION_ID, "different", "other-hash", "key", None,
                         "queued", 0, 3, None))
    connection = FakeConnection([existing])

    with pytest.raises(IdempotencyConflict):
        _run(JobRepository(FakePool(connection)).submit(
            session_id=SESSION_ID, request_text="draw", idempotency_key=JOB_ID
        ))
    assert len(connection.calls) == 3


def test_get_hides_jobs_not_owned_by_session():
    with pytest.raises(JobNotFound):
        _run(JobRepository(FakePool(FakeConnection())).get(
            session_id=SESSION_ID, job_id=JOB_ID
        ))


def test_update_status_persists_terminal_payload_without_thumbnail():
    connection = FakeConnection()
    result = AgentResult(
        agent_status=AgentStatus.OUT_OF_SCOPE,
        reason_codes=[ReasonCode.OUT_OF_SCOPE_REQUEST],
    )

    job = _run(JobRepository(FakePool(connection)).update_status(
        job_id=JOB_ID, status=JobStatus.COMPLETED, attempt=1, result=result
    ))

    update_query, args = connection.calls[0]
    saved = json.loads(args[2])
    assert "thumbnail_url" not in json.dumps(saved)
    assert "completed_at = CASE" in update_query
    assert job.job_status is JobStatus.COMPLETED
    assert job.result == result


@pytest.mark.parametrize(
    ("current_status", "next_status"),
    [
        (JobStatus.RUNNING, JobStatus.VALIDATING),
        (JobStatus.VALIDATING, JobStatus.SEARCHING),
        (JobStatus.SEARCHING, JobStatus.RENDERING),
        (JobStatus.RENDERING, JobStatus.COMPLETED),
        (JobStatus.RUNNING, JobStatus.FAILED),
        (JobStatus.VALIDATING, JobStatus.FAILED),
        (JobStatus.SEARCHING, JobStatus.FAILED),
        (JobStatus.RENDERING, JobStatus.FAILED),
    ],
)
def test_update_status_accepts_only_contractual_forward_and_failure_transitions(
    current_status, next_status
):
    connection = FakeConnection(status=current_status.value)
    terminal_args = (
        {"failure": Failure(failure_code=FailureCode.INTERNAL_CODE_ERROR, user_message="failed")}
        if next_status is JobStatus.FAILED
        else {"result": AgentResult(agent_status=AgentStatus.OUT_OF_SCOPE,
                                    reason_codes=[ReasonCode.OUT_OF_SCOPE_REQUEST])}
        if next_status is JobStatus.COMPLETED
        else {}
    )

    job = _run(JobRepository(FakePool(connection)).update_status(
        job_id=JOB_ID, status=next_status, attempt=1, **terminal_args
    ))

    assert job.job_status is next_status
    assert current_status.value in connection.calls[0][1][5]
    if next_status is JobStatus.COMPLETED:
        assert job.result == terminal_args["result"]
        assert job.failure is None
    elif next_status is JobStatus.FAILED:
        assert job.result is None
        assert job.failure == terminal_args["failure"]


def test_update_status_rejects_regular_completion_from_validating():
    connection = FakeConnection(status=JobStatus.VALIDATING.value)
    result = AgentResult(
        agent_status=AgentStatus.SUCCESS,
        reference_plan={"terms": [], "unresolved_roles": []},
    )

    with pytest.raises(InvalidJobTransition):
        _run(JobRepository(FakePool(connection)).update_status(
            job_id=JOB_ID, status=JobStatus.COMPLETED, attempt=1, result=result
        ))


@pytest.mark.parametrize("agent_status,reason_code", [
    (AgentStatus.UNSAFE_INPUT, ReasonCode.UNSAFE_INPUT),
    (AgentStatus.OUT_OF_SCOPE, ReasonCode.OUT_OF_SCOPE_REQUEST),
])
def test_update_status_accepts_gate_completion_from_validating(agent_status, reason_code):
    connection = FakeConnection(status=JobStatus.VALIDATING.value)
    result = AgentResult(
        agent_status=agent_status,
        reason_codes=[reason_code],
    )

    job = _run(JobRepository(FakePool(connection)).update_status(
        job_id=JOB_ID, status=JobStatus.COMPLETED, attempt=1, result=result
    ))

    assert job.job_status is JobStatus.COMPLETED
    assert job.result == result


@pytest.mark.parametrize(
    ("current_status", "next_status"),
    [
        (JobStatus.RUNNING, JobStatus.SEARCHING),
        (JobStatus.RENDERING, JobStatus.VALIDATING),
        (JobStatus.COMPLETED, JobStatus.FAILED),
        (JobStatus.FAILED, JobStatus.COMPLETED),
    ],
)
def test_update_status_rejects_unallowed_transition(current_status, next_status):
    connection = FakeConnection(status=current_status.value)
    repository = JobRepository(FakePool(connection))
    terminal_args = (
        {"failure": Failure(failure_code=FailureCode.INTERNAL_CODE_ERROR, user_message="failed")}
        if next_status is JobStatus.FAILED
        else {"result": AgentResult(agent_status=AgentStatus.OUT_OF_SCOPE,
                                    reason_codes=[ReasonCode.OUT_OF_SCOPE_REQUEST])}
        if next_status is JobStatus.COMPLETED
        else {}
    )

    with pytest.raises(InvalidJobTransition):
        _run(repository.update_status(
            job_id=JOB_ID, status=next_status, attempt=1, **terminal_args
        ))

    assert "status = ANY($6::text[])" in connection.calls[0][0]


def test_update_status_rejects_missing_job():
    connection = FakeConnection(status=None)

    with pytest.raises(JobNotFound):
        _run(JobRepository(FakePool(connection)).update_status(
            job_id=JOB_ID, status=JobStatus.VALIDATING, attempt=1
        ))


def test_update_status_requires_contractual_terminal_payload():
    repository = JobRepository(FakePool(FakeConnection()))
    failure = Failure(failure_code=FailureCode.INTERNAL_CODE_ERROR, user_message="failed")

    with pytest.raises(ValueError):
        _run(repository.update_status(
            job_id=JOB_ID, status=JobStatus.COMPLETED, attempt=1
        ))
    with pytest.raises(ValueError):
        _run(repository.update_status(
            job_id=JOB_ID, status=JobStatus.QUEUED, attempt=1, failure=failure
        ))


@pytest.mark.parametrize("terminal_status", [JobStatus.COMPLETED, JobStatus.FAILED])
def test_update_status_does_not_overwrite_terminal_job(terminal_status):
    connection = FakeConnection(status=terminal_status.value)
    next_status = JobStatus.FAILED if terminal_status is JobStatus.COMPLETED else JobStatus.COMPLETED
    terminal_payload = (
        {"failure": Failure(failure_code=FailureCode.INTERNAL_CODE_ERROR, user_message="failed")}
        if next_status is JobStatus.FAILED
        else {"result": AgentResult(agent_status=AgentStatus.OUT_OF_SCOPE,
                                    reason_codes=[ReasonCode.OUT_OF_SCOPE_REQUEST])}
    )

    with pytest.raises(InvalidJobTransition):
        _run(JobRepository(FakePool(connection)).update_status(
            job_id=JOB_ID, status=next_status, attempt=1, **terminal_payload
        ))

    query, _ = connection.calls[0]
    assert "status = ANY($6::text[])" in query


def test_update_status_rejects_stale_attempt():
    connection = FakeConnection(status="running", attempt=2)

    with pytest.raises(StaleJobAttempt):
        _run(JobRepository(FakePool(connection)).update_status(
            job_id=JOB_ID, status=JobStatus.VALIDATING, attempt=1
        ))

    assert "AND attempt = $7" in connection.calls[0][0]


def test_extend_lease_is_fenced_by_active_attempt():
    connection = FakeConnection(status="running", attempt=2)
    repository = JobRepository(FakePool(connection))

    _run(repository.extend_lease(job_id=JOB_ID, attempt=2))
    with pytest.raises(StaleJobAttempt):
        _run(repository.extend_lease(job_id=JOB_ID, attempt=1))

    query, args = connection.calls[0]
    assert "AND attempt = $2" in query and "status = ANY($3::text[])" in query
    assert args[:2] == (JOB_ID, 2)


def test_claim_next_uses_transactional_lock_and_updates_attempt_and_lease():
    connection = FakeConnection()

    claimed = _run(JobRepository(FakePool(connection)).claim_next())

    assert claimed["job_id"] == JOB_ID
    assert claimed["status"] == "running"
    assert claimed["attempt"] == 1
    assert claimed["lease_expires_at"] is not None
    assert connection.transaction_count == 1
    query = connection.calls[0][0]
    assert "FOR UPDATE OF queued SKIP LOCKED" in query
    assert "queued.attempt < queued.max_attempts" in query
    assert "queued.next_retry_at <= now()" in query
    assert "earlier.status NOT IN ('completed', 'failed')" in query


def test_concurrent_claims_return_a_job_to_only_one_worker_on_postgres():
    database_url = os.environ.get("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("TEST_DATABASE_URL is required for the PostgreSQL concurrency test")

    async def verify_concurrent_claim():
        application_name = f"claim_test_{uuid.uuid4().hex}"
        admin = await asyncpg.connect(
            database_url, server_settings={"application_name": f"{application_name}_admin"}
        )
        schema = f"claim_test_{uuid.uuid4().hex}"
        lock_key = uuid.uuid4().int & 0x7FFFFFFF
        pool = None
        claim_task = None
        second_task = None
        lock_held = False
        try:
            await admin.execute(f'CREATE SCHEMA "{schema}"')

            async def setup_connection(connection):
                await connection.execute(f'SET search_path TO "{schema}"')
                await connection.execute(
                    "SELECT set_config('application_name', $1, false)", application_name
                )

            pool = await asyncpg.create_pool(
                database_url,
                min_size=2,
                max_size=2,
                setup=setup_connection,
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
                await connection.execute(
                    f"""
                    CREATE FUNCTION hold_claim_for_test() RETURNS trigger
                        LANGUAGE plpgsql AS $$
                        BEGIN
                            PERFORM set_config(
                                'application_name', 'claim_job_' || NEW.job_id::text, true
                            );
                            PERFORM pg_advisory_xact_lock({lock_key}::bigint);
                            RETURN NEW;
                    END;
                    $$
                    """
                )
                await connection.execute(
                    """
                    CREATE TRIGGER hold_claim_for_test
                    AFTER UPDATE OF status ON jobs
                    FOR EACH ROW WHEN (NEW.status = 'running')
                    EXECUTE FUNCTION hold_claim_for_test()
                    """
                )

            repository = JobRepository(pool)
            first_job, _ = await repository.submit(
                session_id=session_id,
                request_text="first request",
                idempotency_key=str(uuid.uuid4()),
            )
            await admin.execute("SELECT pg_advisory_lock($1::bigint)", lock_key)
            lock_held = True
            claim_task = asyncio.create_task(repository.claim_next())

            deadline = asyncio.get_running_loop().time() + 10
            while True:
                waiting = await admin.fetchrow(
                    """
                    SELECT application_name FROM pg_stat_activity
                    WHERE application_name LIKE 'claim_job_%'
                      AND wait_event_type = 'Lock'
                      AND query LIKE '%WITH candidate AS%'
                    LIMIT 1
                    """,
                )
                if waiting:
                    assert waiting["application_name"] == f"claim_job_{first_job.job_id}"
                    break
                if claim_task.done():
                    await claim_task
                    raise AssertionError("first claim did not block in the test trigger")
                if asyncio.get_running_loop().time() >= deadline:
                    raise AssertionError("first claim never reached the held advisory lock")
                await asyncio.sleep(0.01)

            second_task = asyncio.create_task(repository.claim_next())
            try:
                second = await asyncio.wait_for(asyncio.shield(second_task), timeout=10)
            except asyncio.TimeoutError as error:
                blocked = await admin.fetch(
                    """
                    SELECT application_name, state, wait_event_type, wait_event, query
                    FROM pg_stat_activity
                    WHERE application_name LIKE 'claim_test_%'
                      AND state <> 'idle'
                    """,
                )
                raise AssertionError(
                    f"second claim blocked on PostgreSQL lock: "
                    f"{[(row['application_name'], row['wait_event'], row['query'][:80]) for row in blocked]}"
                ) from error
            assert second is None
            assert not claim_task.done()
            await admin.execute("SELECT pg_advisory_unlock($1::bigint)", lock_key)
            lock_held = False
            first = await asyncio.wait_for(claim_task, timeout=5)

            claimed = [job for job in (first, second) if job is not None]
            assert len(claimed) == 1
            assert str(claimed[0]["job_id"]) == first_job.job_id
            async with pool.acquire() as connection:
                rows = await connection.fetch(
                    """
                    SELECT status, attempt, lease_expires_at,
                           lease_expires_at > now()
                               AND lease_expires_at <= now() + interval '31 seconds' AS lease_valid
                    FROM jobs WHERE job_id = $1::uuid
                    """,
                    first_job.job_id,
                )
            assert len(rows) == 1
            assert rows[0]["status"] == "running"
            assert rows[0]["attempt"] == 1
            assert rows[0]["lease_expires_at"] is not None
            assert rows[0]["lease_valid"] is True
        finally:
            if lock_held:
                await admin.execute("SELECT pg_advisory_unlock($1::bigint)", lock_key)
            for task in (claim_task, second_task):
                if task is not None:
                    try:
                        await asyncio.wait_for(asyncio.shield(task), timeout=5)
                    except Exception:
                        task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
            if pool is not None:
                await pool.close()
            await admin.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
            await admin.close()

    asyncio.run(verify_concurrent_claim())
