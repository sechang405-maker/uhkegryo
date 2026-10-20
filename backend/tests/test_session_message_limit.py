"""Real PostgreSQL admission tests, restricted to a disposable named test DB."""
import asyncio
import os
import re
import uuid
from urllib.parse import unquote, urlsplit

import asyncpg
import pytest

from backend.db.migrate import migrate
from backend.services.job_repository import JobRepository, IdempotencyConflict, SessionMessageLimitReached
from backend.services.session_repository import SessionRepository


async def database_case(run):
    url = os.environ.get("SESSION_LIMIT_TEST_DATABASE_URL")
    if not url:
        pytest.skip("SESSION_LIMIT_TEST_DATABASE_URL required")
    name = unquote(urlsplit(url).path.lstrip("/"))
    assert re.fullmatch(r"uhkegryo_session_memory_test_[a-zA-Z0-9_]+", name), "Refusing non-test database"
    admin = await asyncpg.connect(url)
    schema = "quota_test_" + uuid.uuid4().hex
    pool = None
    try:
        actual = await admin.fetchval("SELECT current_database()")
        assert actual == name, "Connected database must match verified disposable target"
        await admin.execute(f'CREATE SCHEMA "{schema}"')
        pool = await asyncpg.create_pool(url, min_size=2, max_size=5,
                                       server_settings={"search_path": schema})
        async with pool.acquire() as connection:
            assert await connection.fetchval("SELECT current_database()") == name
            await migrate(connection)
        await run(pool)
    finally:
        if pool is not None:
            await pool.close()
        await admin.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        await admin.close()


async def seed(pool, count):
    sessions, jobs = SessionRepository(pool), JobRepository(pool)
    token = uuid.uuid4().hex
    sid = await sessions.create_session(token)
    for index in range(count):
        await jobs.submit(session_id=sid, request_text=f"input {index}", idempotency_key=str(uuid.uuid4()))
    return sessions, jobs, token, sid


def test_last_slot_competing_keys_accepts_only_one_job():
    async def case(pool):
        sessions, jobs, token, sid = await seed(pool, 19)
        results = await asyncio.gather(*[
            jobs.submit(session_id=sid, request_text="last", idempotency_key=str(uuid.uuid4()))
            for _ in range(2)], return_exceptions=True)
        assert sum(isinstance(result, SessionMessageLimitReached) for result in results) == 1
        accepted = [result[0] for result in results if isinstance(result, tuple)]
        assert len(accepted) == 1
        # An accepted twentieth input remains claimable and can complete normally.
        await pool.execute("UPDATE jobs SET status='failed', succeeded=false, final_payload_json=$2::jsonb WHERE session_id=$1::uuid AND job_id<>$3::uuid",
                           sid, '{"failure_code":"INTERNAL_CODE_ERROR","user_message":"fixture","retryable":false}', accepted[0].job_id)
        claimed = await jobs.claim_next()
        assert str(claimed["job_id"]) == accepted[0].job_id
        from backend.schemas import AgentResult
        from backend.schemas.enums import AgentStatus, JobStatus, ReasonCode
        await jobs.update_status(job_id=accepted[0].job_id, status=JobStatus.VALIDATING, attempt=1)
        finished = await jobs.update_status(job_id=accepted[0].job_id, status=JobStatus.COMPLETED, attempt=1,
            result=AgentResult(agent_status=AgentStatus.OUT_OF_SCOPE, reason_codes=[ReasonCode.OUT_OF_SCOPE_REQUEST]))
        assert finished.job_status is JobStatus.COMPLETED
        for touch in (False, True):
            view = await sessions.get_session(token, sid, touch=touch)
            assert view["message_count"] == 20 and not view["can_submit"]
            assert view["remaining_messages"] == 0
        assert (await sessions.list_sessions(token))[0]["message_count"] == 20
        assert len(await jobs.history(sid, limit=100)) == 20
    asyncio.run(database_case(case))


def test_same_key_race_and_expired_replay_do_not_charge_again():
    async def case(pool):
        sessions, jobs, token, sid = await seed(pool, 19)
        key = str(uuid.uuid4())
        results = await asyncio.gather(*[jobs.submit(session_id=sid, request_text="last", idempotency_key=key)
                                         for _ in range(3)])
        assert sum(created for _, created in results) == 1
        assert len({job.job_id for job, _ in results}) == 1
        await pool.execute("UPDATE jobs SET idempotency_expires_at=now()-interval '1 day', attempt=3 WHERE session_id=$1::uuid", sid)
        replay, created = await jobs.submit(session_id=sid, request_text="last", idempotency_key=key)
        assert not created and replay.job_id == results[0][0].job_id
        with pytest.raises(IdempotencyConflict):
            await jobs.submit(session_id=sid, request_text="changed", idempotency_key=key)
        assert (await sessions.get_session(token, sid))["message_count"] == 20
    asyncio.run(database_case(case))


def test_rollback_does_not_charge_and_new_session_starts_empty():
    async def case(pool):
        sessions, jobs, token, sid = await seed(pool, 0)
        assert (await sessions.get_session(token, sid))["message_count"] == 0
        async with pool.acquire() as connection:
            with pytest.raises(RuntimeError, match="rollback fixture"):
                async with connection.transaction():
                    await jobs._submit(connection, session_id=sid, request_text="rollback", idempotency_key=str(uuid.uuid4()))
                    raise RuntimeError("rollback fixture")
        assert (await sessions.get_session(token, sid))["message_count"] == 0
        await jobs.submit(session_id=sid, request_text="accepted", idempotency_key=str(uuid.uuid4()))
        assert (await sessions.get_session(token, sid))["message_count"] == 1
    asyncio.run(database_case(case))


def test_legacy_over_limit_history_preserved_and_read_only():
    async def case(pool):
        sessions, jobs, token, sid = await seed(pool, 20)
        await pool.execute("""INSERT INTO jobs(job_id,session_id,request_text,request_text_hash,idempotency_key_hash,
            idempotency_expires_at,status) VALUES($1,$2::uuid,'legacy','legacy','legacy',now(),'queued')""", uuid.uuid4(), sid)
        view = await sessions.get_session(token, sid)
        assert view["message_count"] == 21 and view["remaining_messages"] == 0 and not view["can_submit"]
        with pytest.raises(SessionMessageLimitReached):
            await jobs.submit(session_id=sid, request_text="blocked", idempotency_key=str(uuid.uuid4()))
        assert len(await jobs.history(sid, limit=100)) == 21
    asyncio.run(database_case(case))


def test_real_api_usage_limit_and_idempotency_priority(monkeypatch):
    async def case(pool):
        import httpx
        from backend.main import app
        from backend.routes import agent
        from backend.shared.auth import SESSION_COOKIE_NAME
        sessions, jobs, token, sid = await seed(pool, 19)
        async def repositories():
            return sessions, jobs
        monkeypatch.setattr(agent, "get_repositories", repositories)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test",
                                     cookies={SESSION_COOKIE_NAME: token}) as client:
            key = str(uuid.uuid4())
            async def submit(text="twentieth", request_key=key):
                return await client.post("/api/agent", json={"session_id":sid,"request_text":text},
                                         headers={"Idempotency-Key":request_key})
            accepted = await submit()
            assert accepted.status_code == 202
            assert accepted.json()["message_count"] == 20
            assert accepted.json()["message_limit"] == 20
            assert accepted.json()["remaining_messages"] == 0
            assert accepted.json()["can_submit"] is False
            replay = await submit()
            assert replay.status_code == 202 and replay.json()["job_id"] == accepted.json()["job_id"]
            assert (await submit("changed")).status_code == 409
            rejected = await submit(request_key=str(uuid.uuid4()))
            assert rejected.status_code == 429
            assert rejected.json()["failure_code"] == "session_message_limit_reached"
            assert rejected.json()["retryable"] is False
            assert (await client.get("/api/sessions/"+sid)).json()["message_count"] == 20
            assert (await client.get("/api/sessions")).json()["items"][0]["can_submit"] is False
            new = await client.post("/api/sessions")
            assert new.status_code == 201 and new.json()["message_count"] == 0
    asyncio.run(database_case(case))
