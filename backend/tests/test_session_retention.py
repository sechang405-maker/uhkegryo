from __future__ import annotations

import asyncio
import os
import uuid

import asyncpg
import pytest

from backend.tasks import session_retention
from backend.db.migrate import migrate


def test_cleanup_task_deletes_expired_sessions_and_closes_pool(monkeypatch):
    pool = object()
    created = []
    closed = []
    deleted = []

    async def create_pool(settings):
        created.append(settings)
        return pool

    async def close_pool(received_pool):
        closed.append(received_pool)

    class FakeSessionRepository:
        def __init__(self, received_pool):
            assert received_pool is pool

        async def delete_expired_sessions(self):
            deleted.append(True)
            return 3

    monkeypatch.setattr(session_retention, "create_pool", create_pool)
    monkeypatch.setattr(session_retention, "close_pool", close_pool)
    monkeypatch.setattr(session_retention, "SessionRepository", FakeSessionRepository)

    assert asyncio.run(session_retention.cleanup_expired_sessions()) == 3
    assert created
    assert deleted == [True]
    assert closed == [pool]


def test_cleanup_task_closes_pool_when_delete_fails(monkeypatch):
    pool = object()
    closed = []

    async def create_pool(settings):
        return pool

    async def close_pool(received_pool):
        closed.append(received_pool)

    class FailingSessionRepository:
        def __init__(self, received_pool):
            assert received_pool is pool

        async def delete_expired_sessions(self):
            raise RuntimeError("database unavailable")

    monkeypatch.setattr(session_retention, "create_pool", create_pool)
    monkeypatch.setattr(session_retention, "close_pool", close_pool)
    monkeypatch.setattr(session_retention, "SessionRepository", FailingSessionRepository)

    try:
        asyncio.run(session_retention.cleanup_expired_sessions())
    except RuntimeError as error:
        assert str(error) == "database unavailable"
    else:
        raise AssertionError("cleanup failure must propagate")

    assert closed == [pool]


def test_expired_session_cleanup_cascades_jobs_in_postgres(monkeypatch):
    database_url = os.environ.get("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("TEST_DATABASE_URL is required for the PostgreSQL integration test")

    async def verify_cleanup():
        connection = await asyncpg.connect(database_url)
        transaction = connection.transaction()
        await transaction.start()
        try:
            schema = f"retention_test_{uuid.uuid4().hex}"
            await connection.execute(f'CREATE SCHEMA "{schema}"')
            await connection.execute(f'SET LOCAL search_path TO "{schema}"')
            await migrate(connection)

            session_id = str(uuid.uuid4())
            job_id = str(uuid.uuid4())
            await connection.execute(
                """WITH owner AS (INSERT INTO anonymous_owners(owner_id, session_token_hash)
                   VALUES ($1::uuid, $2) RETURNING owner_id)
                   INSERT INTO sessions(session_id, owner_id) SELECT owner_id,owner_id FROM owner""",
                session_id,
                uuid.uuid4().hex,
            )
            await connection.execute(
                """
                INSERT INTO jobs (
                    job_id, session_id, request_text, request_text_hash,
                    idempotency_key_hash, idempotency_expires_at, status
                ) VALUES ($1::uuid, $2::uuid, $3, $4, $5, now(), 'queued')
                """,
                job_id,
                session_id,
                "raw request text",
                "request-hash",
                "idempotency-hash",
            )
            await connection.execute(
                "UPDATE sessions SET last_activity_at = now() - interval '4 months' WHERE session_id = $1::uuid",
                session_id,
            )

            async def create_test_pool(settings):
                return connection

            async def keep_transaction_open(pool):
                assert pool is connection

            monkeypatch.setattr(session_retention, "get_settings", lambda: object())
            monkeypatch.setattr(session_retention, "create_pool", create_test_pool)
            monkeypatch.setattr(session_retention, "close_pool", keep_transaction_open)

            assert await session_retention.cleanup_expired_sessions() == 1
            assert await connection.fetchrow(
                "SELECT session_id FROM sessions WHERE session_id = $1::uuid", session_id
            ) is None
            assert await connection.fetchrow(
                "SELECT request_text FROM jobs WHERE job_id = $1::uuid", job_id
            ) is None
        finally:
            await transaction.rollback()
            await connection.close()

    asyncio.run(verify_cleanup())
