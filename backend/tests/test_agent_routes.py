"""`POST /api/agent`·`GET /api/jobs/{job_id}` 계약 테스트.

`docs/specs/api-contract.md`와 `docs/specs/session-job-persistence.md`의 AC를
직접 번호로 대응시킨다. 저장 계층은 인메모리 mock이므로 DB·LLM·외부 API 없이
끝까지 돈다.
"""
from __future__ import annotations
from backend.shared.auth import session_cookie_max_age

import json
import hashlib
import time
import uuid
from types import SimpleNamespace

import asyncpg
import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.routes import agent as agent_route
from backend.shared.auth import SESSION_COOKIE_NAME, hash_session_token
from backend.schemas import JobEnvelope
from backend.schemas.enums import JobStatus
from backend.schemas.models import PROGRESS_POLL_AFTER_MS, RETRY_COUNT_MAX
from backend.services.job_repository import IdempotencyConflict, JobNotFound


class FakeSessionRepository:
    def __init__(self):
        self.sessions = {}

    async def create_session(self, token):
        session_id = str(uuid.uuid4())
        self.sessions[hash_session_token(token)] = session_id
        return session_id

    async def resolve_session(self, token):
        return self.sessions.get(hash_session_token(token)) if token else None

    async def has_owner(self, token):
        return bool(await self.resolve_session(token))

    async def session_for_job(self, token, job_id):
        session_id = await self.resolve_session(token)
        if session_id is None:
            raise JobNotFound
        return session_id


class FakeJobRepository:
    def __init__(self, sessions):
        self.sessions = sessions
        self.jobs = {}
        self.idempotency = {}
        self.submit_error = None
        self.get_error = None

    async def submit(self, *, session_id, request_text, idempotency_key):
        if self.submit_error is not None:
            raise self.submit_error
        key = (session_id, hashlib.sha256(idempotency_key.encode()).hexdigest())
        text_hash = hashlib.sha256(request_text.encode()).hexdigest()
        previous = self.idempotency.get(key)
        if previous and previous["expires_at"] > time.monotonic():
            if previous["text_hash"] != text_hash:
                raise IdempotencyConflict
            return self._envelope(self.jobs[previous["job_id"]]), False

        row = {
            "job_id": str(uuid.uuid4()), "session_id": session_id,
            "request_text": request_text, "request_text_hash": text_hash,
            "attempt": 0, "max_attempts": RETRY_COUNT_MAX,
            "status": JobStatus.QUEUED,
        }
        self.jobs[row["job_id"]] = row
        self.idempotency[key] = {
            "job_id": row["job_id"], "text_hash": text_hash,
            "expires_at": time.monotonic() + 600,
        }
        return self._envelope(row), True

    async def submit_new_session(self, *, session_token, request_text, idempotency_key):
        session_id = str(uuid.uuid4())
        result = await self.submit(
            session_id=session_id,
            request_text=request_text,
            idempotency_key=idempotency_key,
        )
        self.sessions.sessions[hash_session_token(session_token)] = session_id
        return result

    async def get(self, *, session_id, job_id):
        if self.get_error is not None:
            raise self.get_error
        row = self.jobs.get(job_id)
        if row is None or row["session_id"] != session_id:
            raise JobNotFound
        return self._envelope(row)

    @staticmethod
    def _envelope(row):
        return JobEnvelope(
            job_id=row["job_id"], session_id=row["session_id"],
            job_status=row["status"], attempt=max(1, row["attempt"]),
            max_attempts=row["max_attempts"],
            poll_after_ms=PROGRESS_POLL_AFTER_MS, result=None, failure=None,
        )


class FakeRepositories:
    def __init__(self):
        self.sessions = FakeSessionRepository()
        self.jobs = FakeJobRepository(self.sessions)

    async def get(self):
        return self.sessions, self.jobs


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    repositories = FakeRepositories()
    monkeypatch.setattr(agent_route, "get_repositories", repositories.get)
    with TestClient(app) as test_client:
        test_client.repositories = repositories
        yield test_client


def submit(client: TestClient, text: str, key: str | None = None) -> dict:
    """에이전트 요청을 보내고 상태 코드와 본문을 돌려준다."""
    headers = {"Idempotency-Key": key or str(uuid.uuid4())}
    response = client.post("/api/agent", json={"request_text": text}, headers=headers)
    return {"status": response.status_code, "body": response.json(), "headers": response.headers}


# --- AC-01 · 비동기 제출 ---------------------------------------------------


def test_new_session_gets_httponly_cookie_and_202(client: TestClient) -> None:
    """AC-01: 신규 세션은 90일 HttpOnly 쿠키를 받고 202와 queued job을 받는다."""
    result = submit(client, "옷이 아니라 실제 몸매 비율이 가벼워 보이게")

    assert result["status"] == 202
    assert result["body"]["job_status"] == "queued"
    assert result["body"]["poll_after_ms"] == 1000
    assert uuid.UUID(result["body"]["job_id"])

    cookie_header = result["headers"]["set-cookie"]
    assert SESSION_COOKIE_NAME in cookie_header
    assert "HttpOnly" in cookie_header
    assert f"Max-Age={session_cookie_max_age()}" in cookie_header  # 90일


def test_production_response_uses_secure_cookie(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(agent_route, "get_settings", lambda: SimpleNamespace(environment="production"))
    result = submit(client, "서 있는 자세")
    assert result["status"] == 202
    assert "Secure" in result["headers"]["set-cookie"]


def test_existing_cookie_is_reused(client: TestClient) -> None:
    """AC-01: 이미 쿠키가 있으면 새 세션을 만들지 않고 같은 세션을 재사용한다."""
    first = submit(client, "다리는 옆으로 벌리고 서 있는 자세")
    token = client.cookies.get(SESSION_COOKIE_NAME)
    second = submit(client, "이번에는 앉아 있는 모습")

    assert client.cookies.get(SESSION_COOKIE_NAME) == token  # 식별자가 바뀌지 않는다

    first_envelope = client.get(f"/api/jobs/{first['body']['job_id']}").json()
    second_envelope = client.get(f"/api/jobs/{second['body']['job_id']}").json()
    assert first_envelope["session_id"] == second_envelope["session_id"]


# --- session-job-persistence:25 · 활동마다 쿠키 갱신 -------------------------


def test_existing_session_cookie_max_age_is_renewed(client: TestClient) -> None:
    """유효 세션의 활동마다 90일 Max-Age를 다시 내보낸다."""
    first = submit(client, "다리를 벌리고 선 자세")
    token = client.cookies.get(SESSION_COOKIE_NAME)

    second = submit(client, "다리를 벌리고 선 자세", key=str(uuid.uuid4()))
    cookie_header = second["headers"]["set-cookie"]

    assert SESSION_COOKIE_NAME in cookie_header
    assert f"{SESSION_COOKIE_NAME}={token}" in cookie_header  # 같은 토큰
    assert f"Max-Age={session_cookie_max_age()}" in cookie_header  # 90일로 갱신
    assert "HttpOnly" in cookie_header
    assert first["body"]["job_id"] != second["body"]["job_id"]


def test_job_read_renews_cookie(client: TestClient) -> None:
    """조회도 API 활동이므로 쿠키를 갱신한다."""
    created = submit(client, "다리를 옆으로 벌린 자세")
    token = client.cookies.get(SESSION_COOKIE_NAME)

    response = client.get(f"/api/jobs/{created['body']['job_id']}")

    assert f"{SESSION_COOKIE_NAME}={token}" in response.headers["set-cookie"]
    assert f"Max-Age={session_cookie_max_age()}" in response.headers["set-cookie"]


def test_404_still_renews_cookie(client: TestClient) -> None:
    """결과가 404여도 유효 세션의 활동이므로 쿠키는 갱신된다."""
    submit(client, "서 있는 자세")
    token = client.cookies.get(SESSION_COOKIE_NAME)

    response = client.get(f"/api/jobs/{uuid.uuid4()}")

    assert response.status_code == 404
    assert f"{SESSION_COOKIE_NAME}={token}" in response.headers["set-cookie"]


def test_unauthorized_read_does_not_issue_cookie(client: TestClient) -> None:
    """세션이 없으면 갱신할 쿠키도 없다."""
    client.cookies.clear()

    response = client.get(f"/api/jobs/{uuid.uuid4()}")

    assert response.status_code == 401
    assert "set-cookie" not in response.headers


def test_invalid_cookie_is_replaced_by_new_session(client: TestClient) -> None:
    """만료되거나 조작된 쿠키는 새 세션으로 대체한다."""
    created = submit(client, "서 있는 자세")
    job_id = created["body"]["job_id"]
    forged = {"Cookie": f"{SESSION_COOKIE_NAME}=forged-token-value"}

    # 별도 브라우저가 조작된 토큰을 들고 온다. 저장소에는 해시만 있어 매칭되지
    # 않으므로 새 세션이 발급되어야 한다.
    stranger = TestClient(app)
    response = stranger.post(
        "/api/agent",
        json={"request_text": "앉아 있는 자세"},
        headers={"Idempotency-Key": str(uuid.uuid4()), **forged},
    )

    assert response.status_code == 202
    assert "forged-token-value" not in response.headers["set-cookie"]
    # 조작된 토큰은 어떤 세션에도 대응하지 않으므로 404가 아니라 401이다. 세션의
    # 존재 여부를 새지 않는다.
    unknown = stranger.get(f"/api/jobs/{job_id}", headers=forged)
    assert unknown.status_code == 401
    assert unknown.json()["failure_code"] == "session_required"
    # 새로 발급된 세션에는 기존 세션의 job이 보이지 않는다.
    assert stranger.get(f"/api/jobs/{job_id}").status_code == 404
    # 원래 세션은 그대로 자기 job을 본다.
    assert client.get(f"/api/jobs/{job_id}").status_code == 200
    stranger.close()


def test_invalid_request_text_is_422(client: TestClient) -> None:
    """공백만 이루어진 요청은 접수하지 않는다."""
    result = submit(client, "   ")

    assert result["status"] == 422
    assert result["body"]["failure_code"] == "invalid_request_text"
    assert result["body"]["retryable"] is False
    assert result["body"]["user_message"]


def test_request_text_over_500_chars_is_422(client: TestClient) -> None:
    assert submit(client, "가" * 501)["status"] == 422


def test_unknown_field_is_rejected(client: TestClient) -> None:
    """브라우저는 role·term_id·검색어 등을 보내지 않는다(extra="forbid")."""
    response = client.post(
        "/api/agent",
        json={"request_text": "서 있는 자세", "role": "pose"},
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )

    assert response.status_code == 422
    assert response.json()["failure_code"] == "invalid_request_text"


def test_missing_idempotency_key_is_422(client: TestClient) -> None:
    response = client.post("/api/agent", json={"request_text": "서 있는 자세"})

    assert response.status_code == 422
    assert response.json()["failure_code"] == "invalid_request_text"


def test_malformed_idempotency_key_is_422(client: TestClient) -> None:
    """Idempotency-Key는 UUID 형식이어야 한다."""
    result = submit(client, "서 있는 자세", key="not-a-uuid")
    assert result["status"] == 422


# --- AC / session-job-persistence · idempotency ----------------------------


def test_same_request_within_10min_returns_same_job(client: TestClient) -> None:
    """같은 세션·키·원문이면 새 job 없이 기존 job을 반환한다."""
    key = str(uuid.uuid4())
    first = submit(client, "다리를 벌리고 선 자세", key=key)
    second = submit(client, "다리를 벌리고 선 자세", key=key)

    assert first["status"] == 202
    assert second["status"] == 202
    assert first["body"]["job_id"] == second["body"]["job_id"]
    assert second["body"]["job_status"] == "queued"


def test_same_key_different_text_is_409(client: TestClient) -> None:
    """같은 키에 다른 원문이면 409 IDEMPOTENCY_KEY_CONFLICT."""
    key = str(uuid.uuid4())
    submit(client, "다리를 벌리고 선 자세", key=key)
    conflict = submit(client, "앉아 있는 자세", key=key)

    assert conflict["status"] == 409
    assert conflict["body"]["failure_code"] == "idempotency_key_conflict"
    assert conflict["body"]["retryable"] is False


def test_different_key_creates_new_job(client: TestClient) -> None:
    first = submit(client, "서 있는 자세", key=str(uuid.uuid4()))
    second = submit(client, "서 있는 자세", key=str(uuid.uuid4()))

    assert first["body"]["job_id"] != second["body"]["job_id"]


# --- AC-06 · queued polling ------------------------------------------------


def test_job_read_returns_queued_envelope(client: TestClient) -> None:
    created = submit(client, "다리를 옆으로 벌린 자세")
    response = client.get(f"/api/jobs/{created['body']['job_id']}")

    assert response.status_code == 200
    envelope = response.json()
    assert envelope["job_status"] == "queued"
    assert envelope["poll_after_ms"] == 1000
    assert envelope["failure"] is None
    assert envelope["result"] is None
    assert envelope["attempt"] == 1  # 계약상 API는 claim 전에도 1을 노출
    assert envelope["max_attempts"] == 3
    stored = client.repositories.jobs.jobs[created["body"]["job_id"]]
    assert stored["attempt"] == 0
    token = client.cookies.get(SESSION_COOKIE_NAME)
    assert token not in client.repositories.sessions.sessions
    assert hash_session_token(token) in client.repositories.sessions.sessions


def test_job_read_without_cookie_is_401(client: TestClient) -> None:
    created = submit(client, "서 있는 자세")
    client.cookies.clear()

    response = client.get(f"/api/jobs/{created['body']['job_id']}")

    assert response.status_code == 401
    assert response.json()["failure_code"] == "session_required"


def test_job_of_other_session_is_404(client: TestClient) -> None:
    """소유하지 않은 job은 없는 job과 같은 404를 준다."""
    owner = TestClient(app)
    created = submit(owner, "서 있는 자세")

    submit(client, "앉아 있는 자세")  # 이 브라우저에도 유효한 세션을 만든다
    response = client.get(f"/api/jobs/{created['body']['job_id']}")

    assert response.status_code == 404
    assert response.json()["failure_code"] == "job_not_found"
    owner.close()


def test_unknown_job_is_404(client: TestClient) -> None:
    submit(client, "서 있는 자세")

    response = client.get(f"/api/jobs/{uuid.uuid4()}")

    assert response.status_code == 404


# --- AC-04 / misc ----------------------------------------------------------


def test_health_still_works(client: TestClient) -> None:
    assert client.get("/health").json() == {"status": "ok"}


def test_openapi_documents_both_endpoints(client: TestClient) -> None:
    """`/docs`에서 계약과 오류 모델을 확인할 수 있어야 한다."""
    paths = client.get("/openapi.json").json()["paths"]

    assert set(paths) >= {"/api/agent", "/api/jobs/{job_id}", "/health"}


def test_error_body_has_no_extra_fields(client: TestClient) -> None:
    """오류 본문은 ApiError의 세 필드만 갖는다(extra="forbid")."""
    body = submit(client, "   ")["body"]

    assert set(body) == {"failure_code", "user_message", "retryable"}


def test_response_is_json_content_type(client: TestClient) -> None:
    response = client.post(
        "/api/agent",
        json={"request_text": "서 있는 자세"},
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )

    assert response.headers["content-type"].startswith("application/json")
    json.loads(response.text)


@pytest.mark.parametrize("endpoint", ["submit", "read"])
def test_database_connection_errors_return_sanitized_contract_body(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    endpoint: str,
) -> None:
    if endpoint == "read":
        created = submit(client, "서 있는 자세")
        job_id = created["body"]["job_id"]

    async def unavailable():
        raise asyncpg.PostgresConnectionError("private database connection details")

    monkeypatch.setattr(agent_route, "get_repositories", unavailable)
    if endpoint == "submit":
        response = client.post(
            "/api/agent",
            json={"request_text": "서 있는 자세"},
            headers={"Idempotency-Key": str(uuid.uuid4())},
        )
    else:
        response = client.get(f"/api/jobs/{job_id}")

    assert response.status_code == 503
    assert response.json() == {
        "failure_code": "DATABASE_UNAVAILABLE",
        "user_message": "현재 요청을 처리하지 못했습니다. 잠시 후 새 메시지로 다시 시도해 주세요.",
        "retryable": False,
    }


def test_new_session_and_failed_job_submit_leave_no_session(client: TestClient) -> None:
    client.repositories.jobs.submit_error = asyncpg.PostgresConnectionError(
        "private database connection details"
    )

    response = client.post(
        "/api/agent",
        json={"request_text": "서 있는 자세"},
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )

    assert response.status_code == 503
    assert response.json()["failure_code"] == "DATABASE_UNAVAILABLE"
    assert client.repositories.sessions.sessions == {}
