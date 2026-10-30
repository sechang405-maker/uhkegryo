"""Read-only card searches; docs/specs/term-search-api.md."""
import asyncio
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from backend.schemas.enums import FailureCode, ReasonCode, Role
from backend.schemas.models import TermResult
from backend.routes.agent import _database_call, _owner, get_repositories, require_conversation_action
from backend.services.failure_mapping import OperationalFailure
from backend.services.personal_term_repository import PersonalTermNotFound, PersonalTermRepository
from backend.services.pinterest_widget import PinterestWidgetClient, PinterestWidgetProvider
from backend.services.response_assembler import RoleSearchOutcome
from backend.services.portfolio_budget import PortfolioActionBudget, PortfolioActionBudgetExceeded
from backend.services.search_url_builder import build_search_url
from backend.services.searxng_pinterest_search import SearXNGPinterestSearchProvider
from backend.shared.config import get_settings

router = APIRouter(tags=["term-search"])
SEARCH_TIMEOUT_SECONDS = 25


def require_user_description(snapshot, term_id: str) -> tuple[dict, str]:
    """Return reviewed UI copy without ever exposing the internal answer draft."""
    feedback = snapshot.feedback.get(term_id)
    plain_meaning = feedback.get("plain_meaning_ko") if feedback else None
    if not isinstance(plain_meaning, str) or not plain_meaning.strip():
        raise HTTPException(503, "이 용어의 설명을 준비하지 못했습니다. 잠시 후 다시 시도해 주세요.")
    return feedback, plain_meaning


class TermSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    term_id: str = Field(min_length=1, max_length=120, strict=True)
    suffix: Literal["drawing", "sketch", "mannequinization"] = "drawing"
    exclude_pin_ids: list[Annotated[str, StringConstraints(strict=True, pattern=r'^(?:[0-9]{1,64}|e1_[A-Za-z0-9_-]{1,200})$')]] = Field(default_factory=list, max_length=64)


def get_search_provider(suffix: str, *, exclude_pin_ids=()) -> PinterestWidgetProvider:
    from backend.services.public_http import current_resources
    resources = current_resources()
    if resources is not None:
        return resources.search_provider(get_settings().searxng_base_url, suffix, exclude_pin_ids=exclude_pin_ids)
    return PinterestWidgetProvider(
        SearXNGPinterestSearchProvider(base_url=get_settings().searxng_base_url, suffix=suffix,
                                      exclude_pin_ids=exclude_pin_ids, candidate_limit=24),
        PinterestWidgetClient(),
    )


async def resolve_personal_search_card(
    request: Request, response: Response, term_id: str,
) -> tuple[dict, dict]:
    """Resolve owner-controlled active values; never trust client copy or query text."""
    sessions, _ = await _database_call(get_repositories())
    token = await _owner(request, response, sessions)
    repository = PersonalTermRepository(sessions._pool)
    try:
        saved = await _database_call(repository.get_active_term(token, term_id))
    except PersonalTermNotFound:
        raise HTTPException(404, "검색할 수 있는 용어를 찾을 수 없습니다.") from None
    if not saved.query_fragments_en:
        raise HTTPException(409, "저장된 영어 검색 표현이 없어 검색할 수 없습니다.")
    return ({
        "role": saved.role.value,
        "label_ko": saved.label_ko,
        "label_en": saved.label_en,
        "query_fragments": saved.query_fragments_en,
        "look_for": saved.reference_checkpoints_ko,
    }, {
        "plain_meaning_ko": saved.plain_meaning_ko,
        "selection_reason_template_ko": "내가 저장한 개인 용어",
        "reference_checkpoints_ko": saved.reference_checkpoints_ko,
    })


@router.post("/api/term-search", response_model=TermResult)
async def search_term(payload: TermSearchRequest, request: Request, response: Response) -> TermResult:
    settings = get_settings()
    if getattr(settings, 'is_portfolio', False):
        require_conversation_action(request, 'term-search')
    if settings.llm_backend == 'codex-cli' and not settings.searxng_base_url:
        raise HTTPException(503, '로컬 이미지 검색이 연결되지 않았습니다. SearXNG 실행 설정을 확인해 주세요.')
    snapshot = request.app.state.catalog
    card = snapshot.get_active(payload.term_id)
    personal_feedback = None
    if card is None and payload.term_id.startswith("personal_"):
        card, personal_feedback = await resolve_personal_search_card(
            request, response, payload.term_id)
    if card is None:
        raise HTTPException(404, "사용 가능한 용어를 찾을 수 없습니다.")
    if snapshot.is_direct_search_disabled(payload.term_id):
        raise HTTPException(409, "이 용어는 직접 검색할 수 없습니다.")
    feedback, plain_meaning = ((personal_feedback, personal_feedback["plain_meaning_ko"])
                               if personal_feedback is not None
                               else require_user_description(snapshot, payload.term_id))
    slots = request.app.state.term_search_slots
    if slots.locked():
        raise HTTPException(429, "검색 중입니다. 잠시 후 다시 시도해 주세요.",
                            headers={"Retry-After": "1"})
    await slots.acquire()
    role = Role(card["role"])
    try:
        if getattr(settings, "is_portfolio", False):
            sessions, _ = await _database_call(get_repositories())
            try:
                await _database_call(PortfolioActionBudget(
                    sessions._pool,
                    resource="term_search",
                    limit=settings.portfolio_daily_term_search_limit,
                ).reserve())
            except PortfolioActionBudgetExceeded:
                raise HTTPException(
                    429,
                    "오늘의 공개 체험 이미지 검색 80회를 모두 사용했습니다. UTC 자정 뒤 다시 시도해 주세요.",
                ) from None
        async with asyncio.timeout(SEARCH_TIMEOUT_SECONDS):
            provider = get_search_provider(payload.suffix, **(
                {'exclude_pin_ids': tuple(payload.exclude_pin_ids)} if payload.exclude_pin_ids else {}))
            outcome = await provider.search(role, tuple(card["query_fragments"]))
    except TimeoutError:
        outcome = RoleSearchOutcome(role=role, code=ReasonCode.PIN_SEARCH_UNAVAILABLE,
                                    search_failure='temporary', retryable=True)
    except OperationalFailure as error:
        if error.failure_code is FailureCode.CONFIGURATION_ERROR:
            raise HTTPException(503, "검색 서비스 설정을 확인해 주세요.") from None
        outcome = RoleSearchOutcome(role=role, code=ReasonCode.PIN_SEARCH_UNAVAILABLE)
    finally:
        slots.release()
    response.headers["Cache-Control"] = "no-store"
    return TermResult(
        role=role, term_id=payload.term_id, label_ko=card["label_ko"], label_en=card["label_en"],
        plain_meaning_ko=plain_meaning,
        selection_reason=feedback.get("selection_reason_template_ko"),
        reference_checkpoints=feedback.get("reference_checkpoints_ko", card["look_for"]),
        search_url=build_search_url(card["query_fragments"], suffix=payload.suffix),
        pins=outcome.pins[:8], reason_codes=[outcome.code] if outcome.code else [],
        search_failure=outcome.search_failure, retryable=outcome.retryable,
        retry_after_seconds=outcome.retry_after_seconds,
    )
