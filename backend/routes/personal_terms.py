"""Owner-scoped API for generating, reviewing, and explicitly saving personal terms."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict

from backend.routes.agent import _database_call, _owner, get_repositories, require_conversation_action
from backend.schemas.personal_terms import PersonalTermRecord, PersonalTermUpdate, SourceInput
from backend.services.personal_term_generator import (
    PersonalTermGenerationFailed,
    PersonalTermGenerationInProgress,
    PersonalTermGenerationRetryRequired,
    PersonalTermGenerator,
)
from backend.services.personal_term_repository import (
    PersonalTermIdempotencyConflict,
    PersonalTermNotFound,
    PersonalTermRepository,
    PersonalTermStateConflict,
)

router = APIRouter(prefix="/api/personal-terms", tags=["personal-terms"])


class ProposalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_input: SourceInput
    retry_failed: bool = False


class DuplicateWarningResponse(BaseModel):
    source: str
    term_id: str
    label_ko: str
    match_kind: str


class ProposalResponse(BaseModel):
    term: PersonalTermRecord
    duplicate_warnings: list[DuplicateWarningResponse]


async def resolve_services(request: Request):
    sessions, _ = await _database_call(get_repositories())
    pool = sessions._pool
    repository = PersonalTermRepository(pool)
    generator = PersonalTermGenerator(repository, request.app.state.catalog)
    return sessions, repository, generator


async def _token(request: Request, response: Response, sessions: Any) -> str:
    return await _owner(request, response, sessions)


@router.post("/proposals", response_model=ProposalResponse, status_code=201)
async def generate_proposal(
    payload: ProposalRequest,
    request: Request,
    response: Response,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    require_conversation_action(request, "personal-term-generate")
    if not idempotency_key or not idempotency_key.strip() or len(idempotency_key) > 200:
        raise HTTPException(422, "요청 식별자가 필요합니다.")
    sessions, repository, generator = await resolve_services(request)
    token = await _token(request, response, sessions)
    try:
        proposal = await generator.propose(
            token, payload.source_input, idempotency_key=idempotency_key,
            retry_failed=payload.retry_failed,
        )
    except PersonalTermIdempotencyConflict:
        raise HTTPException(409, "같은 요청 번호가 다른 설명에 사용되었습니다.") from None
    except PersonalTermGenerationInProgress:
        raise HTTPException(409, "이 용어 초안을 생성하는 중입니다.") from None
    except PersonalTermGenerationRetryRequired:
        raise HTTPException(409, "이전 생성이 실패했습니다. 다시 시도해 주세요.") from None
    except PersonalTermGenerationFailed:
        raise HTTPException(502, "AI 초안을 만들지 못했습니다. 입력을 확인하고 다시 시도해 주세요.") from None
    except PersonalTermNotFound:
        raise HTTPException(404, "개인 용어를 찾을 수 없습니다.") from None
    return ProposalResponse(
        term=proposal.record,
        duplicate_warnings=[DuplicateWarningResponse(**warning.__dict__) for warning in proposal.duplicate_warnings],
    )


@router.get("")
async def list_personal_terms(request: Request, response: Response):
    sessions, repository, _ = await resolve_services(request)
    token = await _token(request, response, sessions)
    return {"items": await _database_call(repository.list_terms(token))}


@router.patch("/{term_id}", response_model=PersonalTermRecord)
async def update_personal_term(
    term_id: str, payload: PersonalTermUpdate, request: Request, response: Response,
):
    require_conversation_action(request, "personal-term-edit")
    sessions, repository, _ = await resolve_services(request)
    token = await _token(request, response, sessions)
    try:
        return await _database_call(repository.update_term(token, term_id, payload))
    except PersonalTermNotFound:
        raise HTTPException(404, "개인 용어를 찾을 수 없습니다.") from None
    except PersonalTermStateConflict:
        raise HTTPException(409, "저장된 용어의 카테고리는 변경할 수 없습니다.") from None


@router.post("/{term_id}/confirm", response_model=PersonalTermRecord)
async def confirm_personal_term(term_id: str, request: Request, response: Response):
    require_conversation_action(request, "personal-term-confirm")
    sessions, repository, _ = await resolve_services(request)
    token = await _token(request, response, sessions)
    try:
        return await _database_call(repository.confirm_term(token, term_id))
    except PersonalTermNotFound:
        raise HTTPException(404, "개인 용어를 찾을 수 없습니다.") from None
    except PersonalTermStateConflict:
        raise HTTPException(409, "검토할 수 있는 초안 상태가 아닙니다.") from None
