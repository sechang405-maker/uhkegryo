"""FastAPI 진입점 (공개 API 전용).

LLM 호출은 여기가 아니라 services/ 아래 한곳에 모으세요.
3차 프로젝트에서 그 자리에 RAG 그래프가 들어옵니다 — 호출부가 흩어져 있으면 그때 전부 뜯어야 합니다.

MCP는 별도 서비스(backend/mcp/main.py)로 분리되어 배포됩니다.
"""
import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from backend.routes.agent import ApiContractError, close_result_tracer, router as agent_router
from backend.routes.term_search import router as term_search_router
from backend.shared.auth import set_session_cookie
from backend.services.catalog_repository import CatalogLoadError, load_catalog
from backend.shared.config import get_settings, resolve_term_cards_dir
from backend.services.agent_worker import run_worker
from backend.services.failure_mapping import public_failure
from backend.schemas.enums import FailureCode

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        app.state.catalog = load_catalog(resolve_term_cards_dir(settings))
    except CatalogLoadError as error:
        raise RuntimeError(f"CATALOG_INVALID_AT_STARTUP: {error}") from error
    app.state.term_search_slots = asyncio.Semaphore(2)
    worker_task = asyncio.create_task(run_worker(app.state.catalog))
    try:
        yield
    finally:
        worker_task.cancel()
        await asyncio.gather(worker_task, return_exceptions=True)
        await asyncio.to_thread(close_result_tracer)

app = FastAPI(title="2차 프로젝트 API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.allowed_origins.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(ApiContractError)
async def handle_api_contract_error(request: FastAPI, exc: ApiContractError) -> JSONResponse:
    """계약이 정한 오류 본문(`ApiError`)을 그대로 내보낸다.

    기본 FastAPI 오류는 `{"detail": ...}`이라 프론트가 두 모양을 다뤄야 한다.
    오류 응답은 라우터가 만든 새 응답이라 쿠키 갱신이 함께 실려 있다.
    """
    response = JSONResponse(status_code=exc.status_code, content=exc.error.model_dump())
    if exc.session_token:
        set_session_cookie(response, exc.session_token, settings)
    return response


app.include_router(agent_router)
app.include_router(term_search_router)


@app.exception_handler(Exception)
async def handle_unexpected_error(request, exc: Exception) -> JSONResponse:
    failure = public_failure(exc)
    status = 500 if failure.failure_code is FailureCode.INTERNAL_CODE_ERROR else 503
    return JSONResponse(status_code=status, content=failure.model_dump(mode="json"))


@app.get("/health")
def health() -> dict:
    """채점자와 배포 환경이 서비스 상태를 확인하는 곳."""
    return {"status": "ok"}


# 실제 Job worker가 LLM adapter → resolver → response assembler를 실행한다.
# Pinterest 검색 결과 연결은 후속 작업에서 worker의 searching 단계에 추가한다.
