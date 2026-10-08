import asyncio
import json
import uuid
from types import SimpleNamespace
from contextlib import contextmanager

import asyncpg
import httpx
import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.routes import agent
from backend.db import migrate as migration
from backend.schemas.enums import FailureCode as Code, ReasonCode, Role
from backend.services.catalog_repository import CatalogLoadError
from backend.services.failure_mapping import FAILURE_MESSAGE, OperationalFailure, classify_failure, public_failure
from backend.services.job_retry_recovery import JobRetryRecovery, should_retry
from backend.services.job_trace import AttemptTrace, JobTracer
from backend.services.llm import LLMConfigurationError, LLMTimeout
from backend.services.searxng_pinterest_search import SearXNGPinterestSearchProvider
from backend.services import agent_worker

SECRET = "secret-token postgresql://private:password@host/db"
CASES = [
    (LLMTimeout(SECRET), Code.LLM_TIMEOUT),
    (LLMConfigurationError(SECRET), Code.CONFIGURATION_ERROR),
    (asyncpg.InvalidPasswordError(SECRET), Code.CONFIGURATION_ERROR),
    (asyncpg.UndefinedTableError(SECRET), Code.DATABASE_MIGRATION_ERROR),
    (asyncpg.PostgresConnectionError(SECRET), Code.DATABASE_UNAVAILABLE),
    (asyncpg.CannotConnectNowError(SECRET), Code.DATABASE_UNAVAILABLE),
    (asyncpg.TooManyConnectionsError(SECRET), Code.DATABASE_UNAVAILABLE),
    (CatalogLoadError(SECRET), Code.CATALOG_INVALID_AT_STARTUP),
    (OperationalFailure(Code.JOB_INSTANCE_INTERRUPTED, SECRET), Code.JOB_INSTANCE_INTERRUPTED),
    (RuntimeError(SECRET), Code.INTERNAL_CODE_ERROR),
]


@pytest.mark.parametrize("error,code", CASES)
def test_public_failure_has_only_stable_code_and_fixed_message(error, code):
    failure = public_failure(error)
    assert failure.model_dump(mode="json") == {
        "failure_code": code.value, "user_message": FAILURE_MESSAGE, "retryable": False,
    }
    if code is not Code.LLM_TIMEOUT:
        assert not should_retry(1, 3, error)
    assert SECRET not in failure.model_dump_json()


@pytest.mark.parametrize("error,code", CASES)
def test_persisted_failure_and_trace_use_same_code_without_exception_text(error, code):
    class Connection:
        async def fetchrow(self, query, *args):
            self.payload = json.loads(args[3])
            return {"job_id": "job-1"}

    class Pool:
        def acquire(self):
            return self
        async def __aenter__(self):
            return connection
        async def __aexit__(self, *args):
            pass

    connection = Connection()
    job = {"job_id": "job-1", "attempt": 3, "max_attempts": 3}
    asyncio.run(JobRetryRecovery(Pool()).handle_attempt_failure(**job, error=error))
    recorded = {}
    trace = AttemptTrace(JobTracer(), SimpleNamespace(update=lambda **data: recorded.update(data)))
    trace.failed(job, error)
    assert connection.payload["failure_code"] == recorded["output"]["failure_code"] == code.value
    assert SECRET not in json.dumps({"payload": connection.payload, "trace": recorded})


@pytest.mark.parametrize("error,code,status", [
    (asyncpg.InvalidPasswordError(SECRET), Code.CONFIGURATION_ERROR, 503),
    (asyncpg.UndefinedColumnError(SECRET), Code.DATABASE_MIGRATION_ERROR, 503),
    (OSError(SECRET), Code.DATABASE_UNAVAILABLE, 503),
    (asyncpg.CannotConnectNowError(SECRET), Code.DATABASE_UNAVAILABLE, 503),
    (asyncpg.TooManyConnectionsError(SECRET), Code.DATABASE_UNAVAILABLE, 503),
    (RuntimeError(SECRET), Code.INTERNAL_CODE_ERROR, 500),
])
def test_api_errors_are_sanitized(monkeypatch, error, code, status):
    async def fail():
        raise error
    monkeypatch.setattr(agent, "get_repositories", fail)
    response = TestClient(app, raise_server_exceptions=False).post(
        "/api/agent", json={"request_text": "서 있는 자세"},
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )
    assert response.status_code == status
    assert response.json() == {"failure_code": code.value, "user_message": FAILURE_MESSAGE, "retryable": False}
    assert SECRET not in response.text


def test_migration_failure_is_classified_and_sanitized(monkeypatch):
    async def fail(connection):
        raise RuntimeError(SECRET)
    monkeypatch.setattr(migration, "_migrate", fail)
    with pytest.raises(OperationalFailure) as caught:
        asyncio.run(migration.migrate(object()))
    assert classify_failure(caught.value) is Code.DATABASE_MIGRATION_ERROR
    assert SECRET not in str(caught.value)


@pytest.mark.parametrize("error,code", [
    (TimeoutError(SECRET), Code.SEARCH_TIMEOUT),
    (httpx.HTTPStatusError(SECRET, request=httpx.Request("GET", "https://example.test"),
                           response=httpx.Response(429)), Code.SEARCH_RATE_LIMITED),
    (RuntimeError(SECRET), Code.SEARCH_UPSTREAM_UNAVAILABLE),
])
def test_search_failure_keeps_partial_result_contract_and_safe_log(caplog, error, code):
    async def fail(url, params):
        raise error
    outcome = asyncio.run(SearXNGPinterestSearchProvider(
        base_url="http://searxng", json_loader=fail,
    ).search(Role.POSE, ("standing",)))
    assert outcome.code is ReasonCode.PIN_SEARCH_UNAVAILABLE
    assert caplog.records[-1].failure_code == code.value
    assert SECRET not in caplog.text
    assert caplog.records[-1].exc_info is None


@pytest.mark.parametrize("error_type", [OSError, asyncpg.CannotConnectNowError, asyncpg.TooManyConnectionsError])
def test_lost_database_heartbeat_is_traced_as_database_failure(monkeypatch, snapshot_factory, error_type):
    recorded = {}
    trace = AttemptTrace(JobTracer(), SimpleNamespace(update=lambda **data: recorded.update(data)))
    @contextmanager
    def attempt(job):
        yield trace
    class Jobs:
        async def claim_next(self):
            return {"job_id": "job", "attempt": 1, "max_attempts": 3}
        async def extend_lease(self, **kwargs):
            raise error_type(SECRET)
    async def blocked(*args):
        await asyncio.Future()
    monkeypatch.setattr(agent_worker, "JobRepository", lambda pool: Jobs())
    worker = agent_worker.AgentJobWorker(object(), snapshot_factory([]),
        tracer=SimpleNamespace(attempt=attempt), heartbeat_interval=0.001)
    monkeypatch.setattr(worker, "_process_claimed", blocked)
    with pytest.raises(OperationalFailure) as caught:
        asyncio.run(worker.run_once())
    assert classify_failure(caught.value) is Code.DATABASE_UNAVAILABLE
    assert recorded["output"]["failure_code"] == Code.DATABASE_UNAVAILABLE.value
    assert SECRET not in json.dumps(recorded)


def test_missing_search_dependency_is_configuration_failure():
    async def fail(url, params):
        raise ModuleNotFoundError(SECRET)
    with pytest.raises(OperationalFailure) as caught:
        asyncio.run(SearXNGPinterestSearchProvider(
            base_url="http://searxng", json_loader=fail,
        ).search(Role.POSE, ("standing",)))
    assert classify_failure(caught.value) is Code.CONFIGURATION_ERROR
