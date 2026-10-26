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
from backend.services.quota_repository import QuotaExceeded, QuotaRepository
from backend.shared.config import get_settings

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
    settings = get_settings()
    quota = QuotaRepository(pool) if settings.auth_mode == "google_invite" else None
    generator = None if settings.login_test_mode else PersonalTermGenerator(
        repository, request.app.state.catalog, quota=quota
    )
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
    if get_settings().login_test_mode:
        raise HTTPException(
            503,
            "로그인 확인 모드에서는 AI 용어 초안을 만들 수 없습니다.",
        )
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
    except QuotaExceeded:
        raise HTTPException(429, "\uacc4\uc815\uc758 AI \uc694\uccad \ud69f\uc218\ub97c \ubaa8\ub450 \uc0ac\uc6a9\ud588\uc2b5\ub2c8\ub2e4.") from None
    return ProposalResponse(
        term=proposal.record,
        duplicate_warnings=[DuplicateWarningResponse(**warning.__dict__) for warning in proposal.duplicate_warnings],
    )


@router.get("")
async def list_personal_terms(
    request: Request, response: Response, include_deleted: bool = False,
):
    sessions, repository, _ = await resolve_services(request)
    token = await _token(request, response, sessions)
    return {
        "items": await _database_call(
            repository.list_terms(token, include_deleted=include_deleted)
        )
    }


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


@router.delete("/{term_id}", response_model=PersonalTermRecord)
async def delete_personal_term(term_id: str, request: Request, response: Response):
    require_conversation_action(request, "personal-term-delete")
    sessions, repository, _ = await resolve_services(request)
    token = await _token(request, response, sessions)
    try:
        return await _database_call(repository.soft_delete(token, term_id))
    except PersonalTermNotFound:
        raise HTTPException(404, "개인 용어를 찾을 수 없습니다.") from None
    except PersonalTermStateConflict:
        raise HTTPException(409, "생성 중이거나 실패한 용어는 이 목록에서 삭제할 수 없습니다.") from None


@router.post("/{term_id}/restore", response_model=PersonalTermRecord)
async def restore_personal_term(term_id: str, request: Request, response: Response):
    require_conversation_action(request, "personal-term-restore")
    sessions, repository, _ = await resolve_services(request)
    token = await _token(request, response, sessions)
    try:
        return await _database_call(repository.restore_term(token, term_id))
    except PersonalTermNotFound:
        raise HTTPException(404, "복구할 개인 용어를 찾을 수 없습니다.") from None
    except PersonalTermStateConflict:
        raise HTTPException(409, "복구할 수 있는 삭제 상태가 아닙니다.") from None


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
