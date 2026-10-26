"""Account quota and administrator controls for invite-only demo mode."""

from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from backend.schemas.demo_accounts import (
    AccountUsage,
    AdminAccountSummary,
    AdminIdentityTransferSummary,
    InviteRecord,
)
from backend.services.demo_account_repository import (
    AccountNotFound,
    AccountStateConflict,
    DemoAccountRepository,
)
from backend.services.invite_code_repository import (
    InviteCodeRepository,
    InviteCodeUnavailable,
    TransferUnavailable,
)
from backend.services.quota_repository import AccountUnavailable, QuotaRepository
from backend.shared.config import get_settings


router = APIRouter(tags=["demo-account"])


class InviteIssueRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    beneficiary_label: str = Field(min_length=1, max_length=120)
    admin_note: str | None = Field(default=None, max_length=500)
    initial_limit: int = Field(default=0, ge=0, le=1_000_000)
    expires_at: datetime | None = None


class IssuedInviteResponse(BaseModel):
    raw_code: str
    invite: InviteRecord


class AdminOverviewResponse(BaseModel):
    accounts: list[AdminAccountSummary]
    invites: list[InviteRecord]
    transfers: list[AdminIdentityTransferSummary]


class ReasonRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=2, max_length=300)


class LimitUpdateRequest(ReasonRequest):
    new_limit: int = Field(ge=0, le=1_000_000)
    expected_current_limit: int = Field(ge=0, le=1_000_000)


class StatusUpdateRequest(ReasonRequest):
    status: str = Field(pattern="^(active|disabled)$")
    expected_current_status: str = Field(pattern="^(active|disabled)$")


async def get_admin_services():
    from backend.routes.agent import get_repositories

    sessions, _ = await get_repositories()
    settings = get_settings()
    pool = sessions._pool
    return (
        DemoAccountRepository(pool),
        InviteCodeRepository(
            pool,
            pepper=settings.invite_code_pepper,
            attempt_limit=settings.invite_redeem_attempt_limit,
            attempt_window=timedelta(seconds=settings.invite_redeem_window_seconds),
        ),
        QuotaRepository(pool),
    )


@router.get("/api/account/usage", response_model=AccountUsage)
async def account_usage(request: Request):
    account = _require_account(request)
    *_, quota = await get_admin_services()
    try:
        return await quota.usage(account.account_id)
    except AccountUnavailable:
        raise HTTPException(404, "계정 사용량을 찾을 수 없습니다.") from None


@router.get("/api/admin/demo", response_model=AdminOverviewResponse)
async def admin_overview(request: Request):
    actor = _require_admin(request)
    accounts, invites, _ = await get_admin_services()
    return AdminOverviewResponse(
        accounts=await accounts.list_accounts_for_admin(actor.account_id),
        invites=await invites.list_for_admin(actor.account_id),
        transfers=await invites.list_identity_transfers_for_admin(actor.account_id),
    )


@router.post("/api/admin/demo/invites", response_model=IssuedInviteResponse)
async def issue_invite(payload: InviteIssueRequest, request: Request):
    actor = _require_admin(request)
    _require_action(request, "issue-invite")
    _, invites, _ = await get_admin_services()
    issued = await invites.issue(
        actor.account_id,
        beneficiary_label=payload.beneficiary_label,
        admin_note=payload.admin_note,
        initial_limit=payload.initial_limit,
        expires_at=payload.expires_at,
    )
    return IssuedInviteResponse(raw_code=issued.raw_code, invite=issued.record)


@router.post("/api/admin/demo/invites/{invite_id}/revoke", response_model=InviteRecord)
async def revoke_invite(invite_id: str, payload: ReasonRequest, request: Request):
    actor = _require_admin(request)
    _require_action(request, "revoke-invite")
    _, invites, _ = await get_admin_services()
    try:
        return await invites.revoke(actor.account_id, invite_id, reason=payload.reason)
    except (InviteCodeUnavailable, ValueError):
        raise HTTPException(409, "대기 중인 초대만 폐기할 수 있습니다.") from None


@router.patch("/api/admin/demo/accounts/{account_id}/limit", status_code=204)
async def update_account_limit(account_id: str, payload: LimitUpdateRequest, request: Request):
    actor = _require_admin(request)
    _require_action(request, "change-limit")
    accounts, _, _ = await get_admin_services()
    try:
        await accounts.set_ai_request_limit(
            actor.account_id, account_id, payload.new_limit,
            expected_current_limit=payload.expected_current_limit, reason=payload.reason,
        )
    except AccountNotFound:
        raise HTTPException(404, "계정을 찾을 수 없습니다.") from None
    except AccountStateConflict:
        raise HTTPException(409, "다른 변경이 먼저 반영되었습니다. 목록을 새로 불러오세요.") from None


    return Response(status_code=204)


@router.patch("/api/admin/demo/accounts/{account_id}/status", status_code=204)
async def update_account_status(account_id: str, payload: StatusUpdateRequest, request: Request):
    actor = _require_admin(request)
    _require_action(request, "change-status")
    accounts, _, _ = await get_admin_services()
    try:
        await accounts.set_account_status(
            actor.account_id, account_id, payload.status,
            expected_current_status=payload.expected_current_status, reason=payload.reason,
        )
    except AccountNotFound:
        raise HTTPException(404, "계정을 찾을 수 없습니다.") from None
    except AccountStateConflict:
        raise HTTPException(409, "다른 변경이 먼저 반영되었습니다. 목록을 새로 불러오세요.") from None


    return Response(status_code=204)


@router.post("/api/admin/demo/transfers/{transfer_id}/approve", status_code=204)
async def approve_identity_transfer(transfer_id: str, payload: ReasonRequest, request: Request):
    actor = _require_admin(request)
    _require_action(request, "approve-transfer")
    _, invites, _ = await get_admin_services()
    try:
        await invites.approve_identity_transfer(actor.account_id, transfer_id, reason=payload.reason)
    except (TransferUnavailable, ValueError):
        raise HTTPException(409, "승인할 수 없는 계정 이전 요청입니다.") from None
    return Response(status_code=204)


@router.post("/api/admin/demo/transfers/{transfer_id}/reject", status_code=204)
async def reject_identity_transfer(transfer_id: str, payload: ReasonRequest, request: Request):
    actor = _require_admin(request)
    _require_action(request, "reject-transfer")
    _, invites, _ = await get_admin_services()
    try:
        await invites.reject_identity_transfer(actor.account_id, transfer_id, reason=payload.reason)
    except (TransferUnavailable, ValueError):
        raise HTTPException(409, "처리할 수 없는 계정 이전 요청입니다.") from None
    return Response(status_code=204)


def _require_account(request: Request):
    account = getattr(request.state, "account", None)
    if account is None or account.status != "active":
        raise HTTPException(401, "로그인이 필요합니다.")
    return account


def _require_admin(request: Request):
    account = _require_account(request)
    if account.role != "admin":
        raise HTTPException(403, "관리자만 사용할 수 있습니다.")
    return account


def _require_action(request: Request, action: str) -> None:
    origin = request.headers.get("origin")
    allowed = {value.strip() for value in get_settings().allowed_origins.split(",") if value.strip()}
    allowed.add(str(request.base_url).rstrip("/"))
    if (
        request.headers.get("x-admin-action") != action
        or request.headers.get("sec-fetch-site") == "cross-site"
        or origin is not None and origin not in allowed
    ):
        raise HTTPException(403, "허용되지 않은 관리자 요청입니다.")
