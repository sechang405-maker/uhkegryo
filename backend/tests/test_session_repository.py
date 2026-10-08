from __future__ import annotations

import pytest
import uuid
from contextlib import asynccontextmanager

from backend.services.session_repository import SessionRepository
from backend.shared.auth import hash_session_token


class FakePool:
    def __init__(self, row=None, execute_result="DELETE 0", error=None):
        self.row = row
        self.execute_result = execute_result
        self.error = error
        self.calls = []

    @asynccontextmanager
    async def acquire(self):
        yield self

    @asynccontextmanager
    async def transaction(self):
        yield self

    async def fetchval(self, query, *args):
        self.calls.append((query, args))
        if self.error:
            raise self.error
        return self.row["session_id"] if self.row else None

    async def fetchrow(self, query, *args):
        self.calls.append((query, args))
        if self.error is not None:
            raise self.error
        return {"owner_id": str(uuid.uuid4()), "default_session_id": None}

    async def execute(self, query, *args):
        self.calls.append((query, args))
        if self.error is not None:
            raise self.error
        return self.execute_result


def test_create_session_stores_only_hash_and_returns_uuid():
    pool = FakePool({"session_id": "0d6fe2df-55e4-4ea2-a8fc-44b133a19f3d"})
    repository = SessionRepository(pool)

    result = _run(repository.create_session("opaque-token"))

    assert uuid.UUID(result)
    assert result == pool.calls[1][1][0]
    assert result != "opaque-token"
    query, args = pool.calls[0]
    assert "INSERT INTO anonymous_owners" in query
    assert args[1] == hash_session_token("opaque-token")
    assert args[0] != "opaque-token"
    assert "opaque-token" not in args


def test_resolve_session_hashes_token_without_touching_activity():
    pool = FakePool({"session_id": "session-uuid"})
    repository = SessionRepository(pool)

    result = _run(repository.resolve_session("opaque-token"))

    query, args = pool.calls[0]
    assert result == "session-uuid"
    assert "UPDATE" not in query
    assert "interval '3 months' > now()" in query
    assert args == (hash_session_token("opaque-token"),)


def test_resolve_unknown_token_returns_none():
    pool = FakePool()

    assert _run(SessionRepository(pool).resolve_session("unknown")) is None


def test_delete_expired_sessions_returns_deleted_count():
    pool = FakePool(execute_result="DELETE 3")

    assert _run(SessionRepository(pool).delete_expired_sessions()) == 3
    query, args = pool.calls[0]
    assert "last_activity_at + interval '3 months' <= now()" in query
    assert args == ()


@pytest.mark.parametrize("method", ["create_session", "resolve_session"])
def test_empty_token_fails_before_database_call(method):
    pool = FakePool()
    repository = SessionRepository(pool)

    with pytest.raises(ValueError):
        _run(getattr(repository, method)(""))
    assert pool.calls == []


@pytest.mark.parametrize(
    ("method", "args"),
    [
        ("create_session", ("opaque-token",)),
        ("resolve_session", ("opaque-token",)),
        ("delete_expired_sessions", ()),
    ],
)
def test_database_errors_are_propagated(method, args):
    pool = FakePool(error=RuntimeError("database unavailable"))

    with pytest.raises(RuntimeError, match="database unavailable"):
        _run(getattr(SessionRepository(pool), method)(*args))


def _run(awaitable):
    import asyncio

    return asyncio.run(awaitable)
