"""공개 API 라우터 — `docs/specs/api-contract.md`를 따른다.

세션과 job의 영속화는 PostgreSQL repositories가 맡는다.
"""
from __future__ import annotations

import json
import asyncio
from weakref import WeakKeyDictionary
import uuid
from time import perf_counter
from typing import Annotated, Any

from fastapi import APIRouter, Header, Query, Request, Response, HTTPException, Path
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from backend.schemas import (
    AgentRequest,
    ApiError,
    ApiErrorCode,
    Failure,
    FailureCode,
    JobEnvelope,
    SubmissionResponse,
)
from backend.shared.auth import SESSION_COOKIE_NAME, create_session_token, set_session_cookie
from backend.shared.config import get_settings
from backend.shared.database import close_pool, create_pool
from backend.services.job_repository import (
    IdempotencyConflict,
    PortfolioQueueFull,
    SessionMessageLimitReached,
    JobNotFound,
)
from backend.services.job_repository import JobRepository
from backend.services.job_repository import conversation_uses_ai_quota
from backend.services.session_repository import SessionRepository
from backend.services.session_repository import SessionBusy
from backend.services.personal_term_repository import PersonalTermRepository
from backend.services.personal_catalog import with_personal_terms
from backend.services.failure_mapping import DATABASE_ERRORS, FAILURE_MESSAGE, classify_failure
from backend.services.pinterest_widget import PinterestWidgetClient
from backend.services.job_trace import JobTracer
from backend.services.quota_repository import QuotaExceeded

router = APIRouter(tags=["agent"])
_pool: Any | None = None
_result_tracer: JobTracer | None = None
_widget_clients: WeakKeyDictionary = WeakKeyDictionary()


def get_result_tracer() -> JobTracer:
    global _result_tracer
    if _result_tracer is None:
        _result_tracer = JobTracer.from_settings()
    return _result_tracer


def close_result_tracer() -> None:
    global _result_tracer
    if _result_tracer is not None:
        _result_tracer.shutdown()
        _result_tracer = None


def get_widget_client() -> PinterestWidgetClient:
    from backend.services.public_http import current_resources
    resources = current_resources()
    if resources is not None:
        return resources.result_widget
    loop = asyncio.get_running_loop()
    if loop not in _widget_clients:
        _widget_clients[loop] = PinterestWidgetClient(shared_readers=True)
    return _widget_clients[loop]


async def close_widget_client() -> None:
    client = _widget_clients.pop(asyncio.get_running_loop(), None)
    if client is not None:
        await client.aclose()


def require_conversation_action(request: Request, action: str) -> None:
    settings = get_settings()
    origin = request.headers.get('origin')
    if getattr(settings, 'is_portfolio', False):
        if (
            request.headers.get('x-conversation-action') != action
            or request.headers.get('sec-fetch-site') == 'cross-site'
            or origin != settings.portfolio_public_origin.rstrip('/')
        ):
            raise HTTPException(403, '허용되지 않은 포트폴리오 변경 요청입니다.')
        return
    allowed = {value.strip() for value in settings.allowed_origins.split(',')}
    allowed.add(str(request.base_url).rstrip('/'))
    if (request.headers.get('x-conversation-action') != action
            or request.headers.get('sec-fetch-site') == 'cross-site'
            or (origin is not None and origin not in allowed)):
        raise HTTPException(403, '허용되지 않은 대화 변경 요청입니다.')


@router.post('/api/local/profile')
async def local_profile(request: Request, response: Response):
    settings = get_settings()
    if getattr(settings, 'is_portfolio', False):
        raise HTTPException(status_code=404, detail='Not found')
    require_conversation_action(request, 'profile')
    token = settings.local_profile_token
    if settings.llm_backend != 'codex-cli' or not token:
        return {'persistent': False}
    from backend.local_codex import local_request_allowed
    if not local_request_allowed(request.client.host if request.client else '',
                                 request.headers.get('host',''), request.headers.get('origin')):
        raise HTTPException(403, '로컬 접속만 허용됩니다.')
    sessions, _ = await _database_call(get_repositories())
    await _database_call(sessions.bind_local_profile(token))
    set_session_cookie(response, token, settings)
    return {'persistent': True}


@router.delete('/api/sessions/{session_id}', status_code=204)
async def delete_conversation(session_id: uuid.UUID, request: Request, response: Response):
    require_conversation_action(request, 'delete')
    sessions, _ = await _database_call(get_repositories())
    token = await _owner(request, response, sessions)
    try:
        await _database_call(sessions.delete_session(token, str(session_id)))
    except SessionBusy:
        raise HTTPException(409, '답변 처리 중인 대화는 완료 후 삭제할 수 있습니다.') from None
    response.status_code = 204
    return response


async def get_repositories() -> tuple[SessionRepository, JobRepository]:
    """Return PostgreSQL repositories backed by the process pool."""
    global _pool
    if _pool is None:
        _pool = await create_pool(get_settings())
    settings = get_settings()
    return SessionRepository(_pool), JobRepository(
        _pool,
        max_pending_jobs=(settings.portfolio_max_pending_jobs if settings.is_portfolio else None),
    )


@router.on_event("shutdown")
async def close_database_pool() -> None:
    global _pool
    if _pool is not None:
        await close_pool(_pool)
        _pool = None

IDEMPOTENCY_KEY_HEADER = "Idempotency-Key"

MESSAGES = {
    ApiErrorCode.SESSION_MESSAGE_LIMIT_REACHED: "이 대화에서 질문 20개를 모두 사용했습니다. 새 대화를 시작해 주세요.",
    ApiErrorCode.INVALID_REQUEST_TEXT: "1~500자의 설명을 보내 주세요. 공백만으로는 접수할 수 없습니다.",
    ApiErrorCode.IDEMPOTENCY_KEY_CONFLICT: "같은 요청 번호로 다른 내용을 보냈습니다. 처음 요청의 결과를 확인해 주세요.",
    ApiErrorCode.SESSION_REQUIRED: "이 브라우저에서 시작한 요청의 세션이 없습니다. 처음부터 다시 시도해 주세요.",
    ApiErrorCode.JOB_NOT_FOUND: "요청한 작업을 찾을 수 없습니다.",
    ApiErrorCode.SESSION_NOT_FOUND: "대화를 찾을 수 없거나 만료되었습니다.",
    ApiErrorCode.ACCOUNT_AI_QUOTA_EXCEEDED: "\uacc4\uc815\uc758 AI \uc694\uccad \ud69f\uc218\ub97c \ubaa8\ub450 \uc0ac\uc6a9\ud588\uc2b5\ub2c8\ub2e4.",
    ApiErrorCode.AI_SERVICE_NOT_CONFIGURED: "로그인 확인 모드에서는 AI 대화 기능을 사용할 수 없습니다.",
}

STATUS_CODES = {
    ApiErrorCode.SESSION_MESSAGE_LIMIT_REACHED: 429,
    ApiErrorCode.INVALID_REQUEST_TEXT: 422,
    ApiErrorCode.IDEMPOTENCY_KEY_CONFLICT: 409,
    ApiErrorCode.SESSION_REQUIRED: 401,
    ApiErrorCode.JOB_NOT_FOUND: 404,
    ApiErrorCode.SESSION_NOT_FOUND: 404,
    ApiErrorCode.ACCOUNT_AI_QUOTA_EXCEEDED: 429,
    ApiErrorCode.AI_SERVICE_NOT_CONFIGURED: 503,
}

DATABASE_ERROR_STATUS = 503
DATABASE_ERROR_MESSAGE = FAILURE_MESSAGE
DATABASE_CONNECTION_ERRORS = DATABASE_ERRORS


class ApiContractError(Exception):
    """`ApiError` 본문을 그대로 응답으로 내보내는 예외.

    `session_token`이 있으면 오류 응답에서도 세션 쿠키를 갱신한다. 유효 세션의
    활동이라면 결과가 404여도 달력 기준 3개월 Max-Age를 다시 내보내야 하기 때문이다
    (`session-job-persistence.md:25`).
    """

    def __init__(
        self,
        code: ApiErrorCode | FailureCode,
        session_token: str | None = None,
    ) -> None:
        self.code = code
        self.session_token = session_token
        if isinstance(code, FailureCode):
            self.status_code = DATABASE_ERROR_STATUS
            self.error = Failure(
                failure_code=code,
                user_message=DATABASE_ERROR_MESSAGE,
                retryable=False,
            )
        else:
            self.status_code = STATUS_CODES[code]
            self.error = ApiError(
                failure_code=code,
                user_message=MESSAGES[code],
                retryable=False,
            )
        super().__init__(code.value)


async def _database_call(operation: Any) -> Any:
    try:
        return await operation
    except DATABASE_CONNECTION_ERRORS as error:
        raise ApiContractError(classify_failure(error, context="database")) from None


async def _parse_agent_request(request: Request) -> AgentRequest:
    """요청 본문을 `AgentRequest`로 검증한다.

    FastAPI의 기본 422 본문(`{"detail": ...}`)을 쓰지 않고 계약에 맞는
    `ApiError`를 내보내기 위해 직접 검증한다. `extra="forbid"` 덕에 허용하지 않은
    추가 필드도 여기서 함께 거절된다.
    """
    body = await request.body()
    if not body:
        raise ApiContractError(ApiErrorCode.INVALID_REQUEST_TEXT)
    try:
        payload: Any = json.loads(body)
        return AgentRequest.model_validate(payload)
    except (ValidationError, ValueError):
        raise ApiContractError(ApiErrorCode.INVALID_REQUEST_TEXT) from None


def _parse_idempotency_key(raw: str | None) -> str:
    """`Idempotency-Key`는 UUID 헤더다(`api-contract.md:23`).

    없거나 UUID 형식이 아니면 잘못된 요청으로 다룬다.
    """
    if not raw:
        raise ApiContractError(ApiErrorCode.INVALID_REQUEST_TEXT)
    try:
        return str(uuid.UUID(raw))
    except ValueError:
        raise ApiContractError(ApiErrorCode.INVALID_REQUEST_TEXT) from None


@router.post(
    "/api/agent",
    response_model=SubmissionResponse,
    status_code=202,
    summary="해석 요청을 접수하고 비동기 job을 만든다",
    responses={
        429: {"model": ApiError, "description": "Session message allowance exhausted"},
        409: {"model": ApiError, "description": "같은 요청 번호에 다른 원문"},
        422: {"model": ApiError, "description": "형식이 잘못된 본문 또는 Idempotency-Key"},
        503: {"model": Failure, "description": "데이터 저장소를 사용할 수 없음"},
    },
)
async def submit_agent(
    request: Request,
    response: Response,
    idempotency_key: Annotated[str | None, Header(alias=IDEMPOTENCY_KEY_HEADER)] = None,
) -> SubmissionResponse:
    """새 세션을 발급하거나 기존 세션을 재사용하고 `202`와 queued job을 돌려준다.

    `api-contract.md` AC-01. 재전송이면 새 job을 만들지 않고 기존 job을 돌려준다
    (`session-job-persistence.md:19`).
    """
    payload = await _parse_agent_request(request)
    if getattr(get_settings(), 'is_portfolio', False):
        require_conversation_action(request, 'agent-submit')
    key = _parse_idempotency_key(idempotency_key)
    settings = get_settings()

    if conversation_uses_ai_quota(payload.request_text):
        from backend.local_codex import local_codex_account_allowed
        if not local_codex_account_allowed(
            settings, getattr(request.state, "account", None)
        ):
            raise HTTPException(
                403, "로컬 Codex AI는 승인된 관리자 계정만 사용할 수 있습니다."
            )

    # Reject model-backed work before creating a session/job or reserving quota.
    if (
        getattr(settings, "login_test_mode", False)
        and conversation_uses_ai_quota(payload.request_text)
    ):
        raise ApiContractError(ApiErrorCode.AI_SERVICE_NOT_CONFIGURED)

    sessions, jobs = await _database_call(get_repositories())
    account = getattr(request.state, "account", None)
    quota_account_id = str(account.account_id) if account is not None else None
    raw_cookie = request.cookies.get(SESSION_COOKIE_NAME)
    known = raw_cookie and await _database_call(sessions.has_owner(raw_cookie))
    token = raw_cookie if known else create_session_token()
    session_id = None
    if payload.session_id is not None:
        if not known:
            raise ApiContractError(ApiErrorCode.SESSION_REQUIRED)
        session_id = str(payload.session_id)
        try:
            await _database_call(sessions.get_session(token, session_id))
        except JobNotFound:
            raise ApiContractError(ApiErrorCode.SESSION_NOT_FOUND, token) from None
    elif known:
        session_id = await _database_call(sessions.resolve_session(token))

    try:
        if session_id is None:
            job, _created = await _database_call(
                jobs.submit_new_session(
                    session_token=token,
                    request_text=payload.request_text,
                    idempotency_key=key,
                    **({"quota_account_id": quota_account_id} if quota_account_id else {}),
                )
            )
        else:
            job, _created = await _database_call(
                jobs.submit(
                    session_id=session_id,
                    request_text=payload.request_text,
                    idempotency_key=key,
                    **({"quota_account_id": quota_account_id} if quota_account_id else {}),
                )
            )
    except SessionMessageLimitReached:
        raise ApiContractError(ApiErrorCode.SESSION_MESSAGE_LIMIT_REACHED, token) from None
    except IdempotencyConflict:
        raise ApiContractError(
            ApiErrorCode.IDEMPOTENCY_KEY_CONFLICT, session_token=token
        ) from None
    except JobNotFound:
        raise ApiContractError(ApiErrorCode.SESSION_NOT_FOUND, token) from None
    except QuotaExceeded:
        raise ApiContractError(ApiErrorCode.ACCOUNT_AI_QUOTA_EXCEEDED, token) from None
    except PortfolioQueueFull:
        raise HTTPException(
            429,
            "공개 체험의 대기 요청이 많습니다. 현재 요청이 끝난 뒤 다시 시도해 주세요.",
        ) from None

    # 신규 발급이든 재사용이든 세션 활동이므로 달력 기준 3개월로 갱신한다. 재사용할 때는
    # 토큰을 그대로 내보내 식별자가 바뀌지 않는다(`session-job-persistence.md:25`).
    set_session_cookie(response, token, get_settings())

    try:
        usage = await _database_call(sessions.get_session(token, job.session_id))
    except ApiContractError as error:
        # Admission already committed. Preserve the owner on the replacement error
        # response so retrying this key can recover the same accepted job.
        raise ApiContractError(error.code, session_token=token) from None
    return SubmissionResponse(job_id=job.job_id, **{
        key: usage[key] for key in ("message_count", "message_limit", "remaining_messages", "can_submit")
    })


@router.get(
    "/api/jobs/{job_id}",
    response_model=JobEnvelope,
    summary="job 상태와 종결 결과를 반환한다",
    responses={
        401: {"model": ApiError, "description": "유효한 세션 쿠키 없음"},
        404: {"model": ApiError, "description": "job이 없거나 소유 세션이 아님"},
        503: {"model": Failure, "description": "데이터 저장소를 사용할 수 없음"},
    },
)
async def read_job(
    job_id: str,
    request: Request,
    response: Response,
) -> JobEnvelope:
    """소유 세션만 자신의 job을 읽는다. `api-contract.md` AC-06."""
    started = perf_counter()
    raw_cookie = request.cookies.get(SESSION_COOKIE_NAME)
    if not raw_cookie:
        raise ApiContractError(ApiErrorCode.SESSION_REQUIRED) from None

    database_started = perf_counter()
    sessions, jobs = await _database_call(get_repositories())
    if not await _database_call(sessions.has_owner(raw_cookie)):
        raise ApiContractError(ApiErrorCode.SESSION_REQUIRED) from None
    database_ms = (perf_counter() - database_started) * 1000

    # 조회가 성공하든 404여도 유효 세션의 활동이므로 쿠키를 갱신한다.
    set_session_cookie(response, raw_cookie, get_settings())

    try:
        job_id = str(uuid.UUID(job_id))
        database_started = perf_counter()
        session_id = await _database_call(sessions.session_for_job(raw_cookie, job_id))
        database_ms += (perf_counter() - database_started) * 1000
    except (JobNotFound, ValueError):
        raise ApiContractError(
            ApiErrorCode.JOB_NOT_FOUND, session_token=raw_cookie
        ) from None
    tracer = get_result_tracer()
    with tracer.result_read(job_id, str(session_id)) as metrics:
        try:
            database_started = perf_counter()
            try:
                job = await _database_call(jobs.get(session_id=session_id, job_id=job_id))
            except (JobNotFound, ValueError):
                raise ApiContractError(ApiErrorCode.JOB_NOT_FOUND, session_token=raw_cookie) from None
            finally:
                metrics["database_ms"] = round(database_ms + (perf_counter() - database_started) * 1000, 3)
            metrics["job_status"] = job.job_status.value
            if job.job_status.value == "completed":
                with tracer.phase("result-widget-refresh", trace_context=metrics["trace_context"]) as widget_metrics:
                    job = await get_widget_client().enrich_job(job)
                    terms = job.result.reference_plan.terms if job.result and job.result.reference_plan else []
                    widget_metrics.update(tracer.pin_counts([pin for term in terms for pin in term.pins]))
            return job
        finally:
            metrics["handler_elapsed_ms"] = round((perf_counter() - started) * 1000, 3)


async def _owner(request: Request, response: Response, sessions: SessionRepository) -> str:
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token or not await _database_call(sessions.has_owner(token)):
        raise ApiContractError(ApiErrorCode.SESSION_REQUIRED)
    set_session_cookie(response, token, get_settings())
    return token


@router.post("/api/sessions", status_code=201)
async def create_conversation(request: Request, response: Response):
    if getattr(get_settings(), 'is_portfolio', False):
        require_conversation_action(request, 'session-create')
    sessions, _ = await _database_call(get_repositories())
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token or not await _database_call(sessions.has_owner(token)):
        token = create_session_token()
    session_id = await _database_call(sessions.create_session(token))
    set_session_cookie(response, token, get_settings())
    return await _database_call(sessions.get_session(token, session_id))


@router.get("/api/sessions")
async def list_conversations(request: Request, response: Response,
                             limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0)):
    sessions, _ = await _database_call(get_repositories())
    token = await _owner(request, response, sessions)
    from backend.services.session_titles import title_terms
    items = await _database_call(sessions.list_sessions(token, limit, offset))
    for item in items:
        item['title_terms'] = title_terms(item.get('title_terms'), getattr(request.app.state, 'catalog', None))
    return {"items": items}


@router.get("/api/sessions/{session_id}")
async def open_conversation(session_id: uuid.UUID, request: Request, response: Response):
    sessions, _ = await _database_call(get_repositories())
    token = await _owner(request, response, sessions)
    try:
        return await _database_call(sessions.get_session(token, str(session_id), touch=True))
    except JobNotFound:
        raise ApiContractError(ApiErrorCode.SESSION_NOT_FOUND, token) from None


def _condition_items(state: dict, snapshot) -> list[dict]:
    conditions = {}
    for value in (state.get("constraints") or {}).values():
        if value.get("term_id"):
            conditions[value["term_id"]] = value
    for value in ((state.get("current_topic") or {}).get("terms") or []):
        if value.get("term_id"):
            conditions.setdefault(value["term_id"], value)
    excluded = state.get("excluded_conditions") or {}
    items = []
    for term_id, value in conditions.items():
        card = snapshot.get_active(term_id)
        if card is None or term_id in excluded:
            continue
        items.append({
            "term_id": term_id,
            "role": card["role"],
            "label_ko": card["label_ko"],
            "source_type": card.get("source_type", "team_card"),
        })
    role_order = {role.value: index for index, role in enumerate(snapshot.roles_order)}
    return sorted(items, key=lambda item: (role_order.get(item["role"], 99), item["label_ko"], item["term_id"]))


async def _session_conditions(request: Request, sessions: SessionRepository, session_id: str, state: dict) -> dict:
    personal = PersonalTermRepository(sessions._pool)
    records = await _database_call(personal.list_active_terms_for_session(session_id))
    snapshot = with_personal_terms(request.app.state.catalog, records)
    return {"items": _condition_items(state, snapshot)}


@router.get("/api/sessions/{session_id}/conditions")
async def current_conditions(session_id: uuid.UUID, request: Request, response: Response):
    sessions, _ = await _database_call(get_repositories())
    token = await _owner(request, response, sessions)
    try:
        state = await _database_call(sessions.get_condition_state(token, str(session_id)))
        return await _session_conditions(request, sessions, str(session_id), state)
    except JobNotFound:
        raise ApiContractError(ApiErrorCode.SESSION_NOT_FOUND, token) from None


@router.delete("/api/sessions/{session_id}/conditions/{term_id}")
async def remove_current_condition(
    session_id: uuid.UUID,
    request: Request,
    response: Response,
    term_id: str = Path(min_length=1, max_length=200),
):
    require_conversation_action(request, "remove-condition")
    sessions, _ = await _database_call(get_repositories())
    token = await _owner(request, response, sessions)
    try:
        state = await _database_call(sessions.remove_condition(token, str(session_id), term_id))
        return await _session_conditions(request, sessions, str(session_id), state)
    except SessionBusy:
        raise HTTPException(409, "답변 처리 중에는 검색 조건을 바꿀 수 없습니다. 완료 후 다시 시도해 주세요.") from None
    except JobNotFound:
        raise ApiContractError(ApiErrorCode.SESSION_NOT_FOUND, token) from None


@router.get("/api/sessions/{session_id}/jobs")
async def conversation_history(session_id: uuid.UUID, request: Request, response: Response,
                               limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0),
                               latest: bool = False, before_job_id: uuid.UUID | None = None):
    sessions, jobs = await _database_call(get_repositories())
    token = await _owner(request, response, sessions)
    try:
        await _database_call(sessions.get_session(token, str(session_id)))
        if latest:
            return await _database_call(jobs.history_page(str(session_id), limit, str(before_job_id) if before_job_id else None))
        return {"items": await _database_call(jobs.history(str(session_id), limit, offset))}
    except JobNotFound:
        raise ApiContractError(ApiErrorCode.SESSION_NOT_FOUND, token) from None
