"""Read-only card searches; docs/specs/term-search-api.md."""
import asyncio
from typing import Literal

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from backend.schemas.enums import FailureCode, ReasonCode, Role
from backend.schemas.models import TermResult
from backend.services.failure_mapping import OperationalFailure
from backend.services.pinterest_widget import PinterestWidgetClient, PinterestWidgetProvider
from backend.services.response_assembler import RoleSearchOutcome
from backend.services.search_url_builder import build_search_url
from backend.services.searxng_pinterest_search import SearXNGPinterestSearchProvider
from backend.shared.config import get_settings

router = APIRouter(tags=["term-search"])
SEARCH_TIMEOUT_SECONDS = 25


class TermSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    term_id: str = Field(min_length=1, max_length=120, strict=True)
    suffix: Literal["drawing", "sketch", "mannequinization"] = "drawing"


def get_search_provider(suffix: str) -> PinterestWidgetProvider:
    return PinterestWidgetProvider(
        SearXNGPinterestSearchProvider(base_url=get_settings().searxng_base_url, suffix=suffix),
        PinterestWidgetClient(),
    )


@router.post("/api/term-search", response_model=TermResult)
async def search_term(payload: TermSearchRequest, request: Request, response: Response) -> TermResult:
    snapshot = request.app.state.catalog
    card = snapshot.get_active(payload.term_id)
    if card is None:
        raise HTTPException(404, "사용 가능한 용어를 찾을 수 없습니다.")
    if snapshot.is_direct_search_disabled(payload.term_id):
        raise HTTPException(409, "이 용어는 직접 검색할 수 없습니다.")
    slots = request.app.state.term_search_slots
    if slots.locked():
        raise HTTPException(429, "검색 중입니다. 잠시 후 다시 시도해 주세요.",
                            headers={"Retry-After": "1"})
    await slots.acquire()
    role = Role(card["role"])
    try:
        async with asyncio.timeout(SEARCH_TIMEOUT_SECONDS):
            outcome = await get_search_provider(payload.suffix).search(role, tuple(card["query_fragments"]))
    except TimeoutError:
        outcome = RoleSearchOutcome(role=role, code=ReasonCode.PIN_SEARCH_UNAVAILABLE)
    except OperationalFailure as error:
        if error.failure_code is FailureCode.CONFIGURATION_ERROR:
            raise HTTPException(503, "검색 서비스 설정을 확인해 주세요.") from None
        outcome = RoleSearchOutcome(role=role, code=ReasonCode.PIN_SEARCH_UNAVAILABLE)
    finally:
        slots.release()
    feedback = snapshot.feedback.get(payload.term_id, {})
    response.headers["Cache-Control"] = "no-store"
    return TermResult(
        role=role, term_id=payload.term_id, label_ko=card["label_ko"], label_en=card["label_en"],
        plain_meaning_ko=feedback.get("plain_meaning_ko", card["source_answer_draft"]),
        selection_reason=feedback.get("selection_reason_template_ko"),
        reference_checkpoints=feedback.get("reference_checkpoints_ko", card["look_for"]),
        search_url=build_search_url(card["query_fragments"], suffix=payload.suffix),
        pins=outcome.pins[:8], reason_codes=[outcome.code] if outcome.code else [],
    )
