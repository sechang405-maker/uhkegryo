import asyncio
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import asyncpg
import pytest
import httpx

from backend.services.session_repository import SessionRepository
from backend.services.job_repository import JobRepository, JobNotFound
from backend.shared import auth


def test_calendar_cookie_expiry():
    now = datetime(2026, 1, 31, tzinfo=timezone.utc)
    assert hasattr(auth, "session_cookie_max_age")
    assert auth.session_cookie_max_age(now) == 89 * 86400
    assert auth.session_cookie_max_age(datetime(2026, 7, 31, tzinfo=timezone.utc)) == 92 * 86400


async def database_case(run, *, legacy=False):
    url = os.environ.get("MEMORY_TEST_DATABASE_URL")
    if not url:
        pytest.skip("MEMORY_TEST_DATABASE_URL required for isolated PostgreSQL tests")
    schema = "memory_test_" + uuid.uuid4().hex
    admin = await asyncpg.connect(url)
    await admin.execute(f'CREATE SCHEMA "{schema}"')
    pool = await asyncpg.create_pool(url, server_settings={"search_path": schema})
    try:
        for path in sorted((Path(__file__).parents[1] / "db/migrations").glob("*.sql")):
            if legacy and path.name.startswith("003"):
                break
            await pool.execute(path.read_text(encoding="utf-8"))
        await run(pool)
    finally:
        await pool.close()
        await admin.execute(f'DROP SCHEMA "{schema}" CASCADE')
        await admin.close()


def test_owner_isolation_default_and_expiry():
    async def case(pool):
        sessions, jobs = SessionRepository(pool), JobRepository(pool)
        a = await sessions.create_session("owner-a")
        b = await sessions.create_session("owner-a")
        c = await sessions.create_session("owner-c")
        assert a != b
        assert await sessions.resolve_session("owner-a") == a
        assert {r["session_id"] for r in await sessions.list_sessions("owner-a")} == {a, b}
        with pytest.raises(JobNotFound):
            await sessions.get_session("owner-a", c)
        row = await sessions.get_session("owner-a", a)
        await sessions.list_sessions("owner-a")
        assert (await sessions.get_session("owner-a", a))["last_activity_at"] == row["last_activity_at"]
        job, _ = await jobs.submit(session_id=a, request_text="마른 체형", idempotency_key=str(uuid.uuid4()))
        assert await sessions.session_for_job("owner-a", job.job_id) == a
        await pool.execute("UPDATE sessions SET last_activity_at=now()-interval '4 months' WHERE session_id=$1", uuid.UUID(a))
        assert await sessions.resolve_session("owner-a") is None
        with pytest.raises(JobNotFound):
            await sessions.get_session("owner-a", a, touch=True)
        with pytest.raises(JobNotFound):
            await sessions.session_for_job("owner-a", job.job_id)
        assert await jobs.claim_next() is None
        new, _ = await jobs.submit_new_session(session_token="owner-a", request_text="서 있는 자세", idempotency_key=str(uuid.uuid4()))
        assert str(new.session_id) not in (a, b)
        assert await sessions.resolve_session("owner-a") == new.session_id
    asyncio.run(database_case(case))


def test_existing_cookie_and_jobs_survive_migration():
    async def case(pool):
        from backend.shared.auth import hash_session_token
        sid, jid = uuid.uuid4(), uuid.uuid4()
        await pool.execute("INSERT INTO sessions(session_id,session_token_hash) VALUES($1,$2)",
                           sid, hash_session_token("old-cookie"))
        await pool.execute("""INSERT INTO jobs(job_id,session_id,request_text,request_text_hash,
                           idempotency_key_hash,idempotency_expires_at,status)
                           VALUES($1,$2,'original','hash','key',now(),'queued')""", jid, sid)
        migration = Path(__file__).parents[1] / "db/migrations/003_conversation_owners.sql"
        await pool.execute(migration.read_text(encoding="utf-8"))
        repository = SessionRepository(pool)
        assert await repository.resolve_session("old-cookie") == str(sid)
        assert await repository.session_for_job("old-cookie", str(jid)) == str(sid)
        assert await pool.fetchval("SELECT request_text FROM jobs WHERE job_id=$1", jid) == "original"
    asyncio.run(database_case(case, legacy=True))


def test_conversation_api_and_legacy_default(monkeypatch):
    from backend.main import app
    from backend.routes import agent
    async def case(pool):
        async def repositories():
            return SessionRepository(pool), JobRepository(pool)
        monkeypatch.setattr(agent, "get_repositories", repositories)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            first = await client.post("/api/sessions")
            assert first.status_code == 201
            a = first.json()["session_id"]
            b = (await client.post("/api/sessions")).json()["session_id"]
            for selected in (None, b):
                body = {"request_text": "서 있는 자세"}
                if selected:
                    body["session_id"] = selected
                submitted = await client.post("/api/agent", json=body, headers={"Idempotency-Key": str(uuid.uuid4())})
                assert submitted.status_code == 202
                job = (await client.get("/api/jobs/" + submitted.json()["job_id"])).json()
                assert job["session_id"] == (selected or a)
            rows = (await client.get("/api/sessions")).json()["items"]
            assert len(rows) == 2
            history = (await client.get(f"/api/sessions/{b}/jobs")).json()["items"]
            assert history[0]["request_text"] == "서 있는 자세"
            before = await pool.fetchval("SELECT last_activity_at FROM sessions WHERE session_id=$1", uuid.UUID(b))
            await client.get("/api/jobs/" + history[0]["job_id"])
            assert await pool.fetchval("SELECT last_activity_at FROM sessions WHERE session_id=$1", uuid.UUID(b)) == before
            assert (await client.get(f"/api/sessions/{b}")).status_code == 200
            client.cookies.clear()
            assert (await client.get(f"/api/sessions/{b}")).status_code == 401
    asyncio.run(database_case(case))


def test_default_submit_is_atomic_and_idempotent():
    async def case(pool):
        jobs = JobRepository(pool)
        key = str(uuid.uuid4())
        results = await asyncio.gather(*[
            jobs.submit_new_session(session_token="same-owner", request_text="서 있어", idempotency_key=key)
            for _ in range(4)
        ])
        assert len({r[0].job_id for r in results}) == 1
        assert await pool.fetchval("SELECT count(*) FROM anonymous_owners") == 1
        assert await pool.fetchval("SELECT count(*) FROM sessions") == 1
        assert await pool.fetchval("SELECT count(*) FROM jobs") == 1
    asyncio.run(database_case(case))
