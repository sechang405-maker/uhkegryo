"""MCP 서버: FastMCP(v1.x) 기반 도구 노출.
FastAPI 앱에 마운트되어 `/mcp` 경로로 서비스됨.

카탈로그 로드·검증은 backend/services/catalog_repository.py로 단일화한다 (T17).
TERM_CARD는 시작 시 검증을 통과해야 ready이며, 실패 시 프로세스가 시작하지 않는다 (fail-closed).
"""
from contextlib import asynccontextmanager
import os

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from backend.services.catalog_repository import (
    CatalogSnapshot,
    CatalogLoadError,
    load_catalog,
)
from backend.shared.config import get_settings, resolve_term_cards_dir
from backend.schemas.enums import FailureCode, Role
from backend.services.failure_mapping import OperationalFailure
from backend.services.searxng_pinterest_search import SearXNGPinterestSearchProvider

settings = get_settings()

# TERM_CARD 카탈로그 경로 (환경변수/Docker/로컬 자동 해결)
CATALOG_DIR = resolve_term_cards_dir(settings)

# 전역 카탈로그 상태 (시작 시 1회 로드, 요청 중 재읽기 없음)
_snapshot: CatalogSnapshot | None = None


def load_catalog_snapshot() -> None:
    """시작 시 카탈로그 검증 로드. 실패 시 프로세스 시작 거부 (CATALOG_INVALID_AT_STARTUP)."""
    global _snapshot
    try:
        _snapshot = load_catalog(CATALOG_DIR)
    except CatalogLoadError as e:
        raise RuntimeError(
            f"TERM_CARD catalog failed validation at startup: {e}"
        ) from e


# 시작 시 카탈로그 로드 (실패 시 예외 전파 → 프로세스 크래시)
load_catalog_snapshot()


_allowed_hosts = ["127.0.0.1:*", "localhost:*", "[::1]:*"]
if cloud_host := os.getenv("MCP_ALLOWED_HOST"):
    _allowed_hosts.append(cloud_host)

mcp = FastMCP(
    "illustration-reference-mcp",
    transport_security=TransportSecuritySettings(allowed_hosts=_allowed_hosts),
)


@mcp.tool()
async def get_active_term_card(term_id: str) -> dict:
    """Pydantic 검증 뒤의 활성 term ID에 대한 팀 검수 설명·검색 조각이 필요할 때 사용한다.

    Args:
        term_id: 활성 TERM_CARD ID (예: pose_contrapposto)

    Returns:
        found: 활성 카드 정보 / not_found: TERM_NOT_ACTIVE
    """
    if _snapshot is None:
        return {
            "status": "not_found",
            "reason_code": "CATALOG_INVALID_AT_STARTUP",
            "message": "TERM_CARD catalog failed validation at startup",
        }

    card = _snapshot.get_active(term_id)
    if not card:
        return {
            "status": "not_found",
            "reason_code": "TERM_NOT_ACTIVE",
        }

    # 성공 응답: 문서 계약에 따른 found 구조
    return {
        "status": "found",
        "catalog_version": _snapshot.dataset_version,
        "term": {
            "term_id": card["term_id"],
            "role": card["role"],
            "label_ko": card["label_ko"],
            "label_en": card["label_en"],
            "query_fragments": card["query_fragments"],
            "look_for": card["look_for"],
        },
    }


@mcp.tool()
async def search_pinterest_pins(role: Role, query_fragments: list[str], exclude_pin_ids: list[str] | None = None) -> dict:
    """활성 TERM_CARD 검색 조각으로 Pinterest Pin 링크를 검색한다.

    검증된 카드의 조각만 전달한다. 조각은 공백으로 결합하고 도구가
    `drawing`을 추가해 SearXNG Pinterest 엔진에서 검색한다. Pin ID는 canonical
    Pinterest Pin URL로 반환된다.
    완성 검색어, 사용자 원문, 추가 검색 조건은 전달하지 않는다.

    Args:
        role: 결과를 연결할 역할. `body`, `pose`, `view`, `perspective`, `layout` 중 하나.
        query_fragments: 활성 TERM_CARD에서 가져온 비어 있지 않은 검색어 조각 배열.
        exclude_pin_ids: 전체 교체 시 서버가 전달하는 이전 보드 Pin ID, 최대 40개.

    Returns:
        정상 검색: `role`, 검증된 `pins` 배열(최대 8개), nullable `code`.
        정상 0건은 빈 `pins`와 `PIN_RESULTS_EMPTY`, 검색 장애는 빈 `pins`와
        `PIN_SEARCH_UNAVAILABLE`를 반환한다. 필수 설정 누락은
        `{"failure_code": "CONFIGURATION_ERROR"}`를 반환한다.
        각 Pin은 `pin_id`, `pin_url`, `thumbnail_url`, `status`를 포함한다.
        `_search_trace`는 단일 Pinterest 엔진 요청의 시간·결과 관측 전용 진단이다.
    """
    if exclude_pin_ids and (len(exclude_pin_ids) > 40 or any(
        not pin.isascii() or not pin.isdigit() for pin in exclude_pin_ids
    )):
        return {"failure_code": "INVALID_SEARCH_TERMS"}
    if _snapshot is None or not any(
        card.get("role") == role.value and card.get("query_fragments") == query_fragments
        for card in _snapshot.active_cards.values()
    ):
        return {"failure_code": "INVALID_SEARCH_TERMS"}
    engine_attempts: list[dict] = []
    try:
        outcome = await SearXNGPinterestSearchProvider(
            base_url=settings.searxng_base_url, engine_attempts=engine_attempts,
            exclude_pin_ids=tuple(exclude_pin_ids or ()),
        ).search(Role(role), tuple(query_fragments))
    except OperationalFailure as error:
        if error.failure_code is FailureCode.CONFIGURATION_ERROR:
            return {"failure_code": FailureCode.CONFIGURATION_ERROR.value}
        raise
    return {
        "role": outcome.role.value,
        "pins": [pin.model_dump(mode="json") for pin in outcome.pins],
        "code": outcome.code.value if outcome.code else None,
        "_search_trace": engine_attempts,
    }


def create_mcp_app():
    """FastMCP를 FastAPI 앱에 마운트하여 반환."""
    from fastapi import FastAPI

    streamable_app = mcp.streamable_http_app()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        async with mcp.session_manager.run():
            yield

    mcp_app = FastAPI(title="MCP Server", lifespan=lifespan)

    @mcp_app.get("/health")
    def health() -> dict:
        return {
            "status": "ok" if _snapshot is not None else "error",
            "service": "mcp",
            "catalog_valid": _snapshot is not None,
            "active_cards_count": _snapshot.active_count if _snapshot else 0,
        }

    mcp_app.mount("/", streamable_app)
    return mcp_app


app = create_mcp_app()
