"""Invitation-only Google OIDC endpoints; inactive while AUTH_MODE=local."""

from __future__ import annotations

import httpx
from datetime import timedelta
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, ConfigDict, Field

from backend.services.auth_session_repository import AuthSessionRepository, AuthSessionUnavailable
from backend.services.demo_account_repository import DemoAccountRepository
from backend.services.google_oidc import GoogleOIDCClient, OIDCVerificationError
from backend.services.invite_code_repository import (
    InviteCodeInvalid, InviteCodeRepository, InviteCodeUnavailable, InviteRateLimited,
    TransferUnavailable,
)
from backend.shared.config import get_settings


router = APIRouter(prefix="/api/auth", tags=["auth"])
APP_COOKIE = "session_id"
REGISTRATION_COOKIE = "registration_session"
_http: httpx.AsyncClient | None = None


class InviteRedemption(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(min_length=20, max_length=200)


def auth_frontend_origin() -> str:
    return get_settings().auth_frontend_origin.rstrip("/")


async def get_auth_services():
    global _http
    from backend.routes.agent import get_repositories
    sessions, _ = await get_repositories()
    settings = get_settings()
    if _http is None:
        _http = httpx.AsyncClient(timeout=15, follow_redirects=False)
    auth_sessions = AuthSessionRepository(sessions._pool)
    return (
        DemoAccountRepository(sessions._pool),
        auth_sessions,
        InviteCodeRepository(
            sessions._pool,
            pepper=settings.invite_code_pepper,
            attempt_limit=settings.invite_redeem_attempt_limit,
            attempt_window=timedelta(seconds=settings.invite_redeem_window_seconds),
        ),
        GoogleOIDCClient(
            client_id=settings.google_client_id,
            client_secret=settings.google_client_secret,
            redirect_uri=settings.google_redirect_uri,
            flow_store=auth_sessions,
            http=_http,
        ),
    )


async def close_auth_http() -> None:
    global _http
    if _http is not None:
        await _http.aclose()
        _http = None


@router.get("/google/start")
async def google_start():
    _require_google_mode()
    *_, oidc = await get_auth_services()
    return RedirectResponse(await oidc.authorization_url())


@router.get("/google/callback")
async def google_callback(request: Request, state: str, code: str):
    _require_google_mode()
    accounts, sessions, _, oidc = await get_auth_services()
    current_account = None
    current_token = request.cookies.get(APP_COOKIE)
    if current_token:
        try:
            current_account = await sessions.resolve_app_session(current_token)
        except AuthSessionUnavailable:
            pass
    try:
        identity = await oidc.verify_callback(state=state, code=code)
        existing = await accounts.get_by_google_subject(identity.google_subject)
        if current_account is not None and existing is not None:
            if current_account.account_id != existing.account_id:
                return RedirectResponse(auth_frontend_origin() + "/transfer?error=already-bound")
        account = await accounts.record_google_login(
            identity.google_subject,
            verified_email=identity.verified_email,
            display_name=identity.display_name,
        )
    except OIDCVerificationError:
        raise HTTPException(401, "Google 로그인을 확인할 수 없습니다.") from None
    if account is not None:
        if account.status != "active":
            raise HTTPException(403, "비활성화된 계정입니다.")
        token = await sessions.create_app_session(account.account_id)
        response = RedirectResponse(auth_frontend_origin() + "/")
        _set_cookie(response, APP_COOKIE, token, max_age=30 * 86400)
        response.delete_cookie(REGISTRATION_COOKIE, path="/", samesite="lax")
        return response
    token = await sessions.create_registration_session(
        google_subject=identity.google_subject,
        verified_email=identity.verified_email,
        display_name=identity.display_name,
    )
    response = RedirectResponse(
        auth_frontend_origin() + ("/transfer" if current_account is not None else "/invite")
    )
    _set_cookie(response, REGISTRATION_COOKIE, token, max_age=10 * 60)
    return response


@router.post("/invite/redeem")
async def redeem_invite(payload: InviteRedemption, request: Request):
    _require_google_mode()
    _require_action(request, "redeem")
    token = request.cookies.get(REGISTRATION_COOKIE)
    if not token:
        raise HTTPException(401, "Google 로그인을 먼저 완료해 주세요.")
    _, sessions, invites, _ = await get_auth_services()
    try:
        identity = await sessions.resolve_registration_session(token)
        account = await invites.redeem(
            payload.code,
            google_subject=identity.google_subject,
            verified_email=identity.verified_email,
            display_name=identity.display_name,
            attempt_scope=(
                identity.google_subject
                + ":"
                + (request.client.host if request.client else "unknown")
            ),
        )
        await sessions.consume_registration_session(token)
        app_token = await sessions.create_app_session(account.account_id)
    except InviteRateLimited:
        raise HTTPException(429, "초대 코드 확인 시도가 너무 많습니다. 잠시 뒤 다시 시도해 주세요.") from None
    except (AuthSessionUnavailable, InviteCodeInvalid, InviteCodeUnavailable):
        raise HTTPException(400, "초대 코드를 확인할 수 없습니다.") from None
    response = JSONResponse({"account": account.model_dump(mode="json")})
    _set_cookie(response, APP_COOKIE, app_token, max_age=30 * 86400)
    response.delete_cookie(REGISTRATION_COOKIE, path="/", samesite="lax")
    return response


@router.get("/identity-transfer/status")
async def identity_transfer_status(request: Request):
    _require_google_mode()
    accounts, sessions, _, _ = await get_auth_services()
    app_token = request.cookies.get(APP_COOKIE)
    registration_token = request.cookies.get(REGISTRATION_COOKIE)
    if not app_token or not registration_token:
        raise HTTPException(401, "기존 계정과 새 Google 로그인이 모두 필요합니다.")
    try:
        source = await sessions.resolve_app_session(app_token)
        target = await sessions.resolve_registration_session(registration_token)
        source_account = await accounts.get_account(source.account_id)
    except AuthSessionUnavailable:
        raise HTTPException(401, "계정 이전 확인 시간이 만료되었습니다.") from None
    return {
        "source_email": source_account.email_normalized,
        "source_display_name": source_account.display_name,
        "target_email": target.verified_email,
        "target_display_name": target.display_name,
    }


@router.post("/identity-transfer/request")
async def request_identity_transfer(request: Request):
    _require_google_mode()
    _require_action(request, "request-transfer")
    _, sessions, invites, _ = await get_auth_services()
    app_token = request.cookies.get(APP_COOKIE)
    registration_token = request.cookies.get(REGISTRATION_COOKIE)
    if not app_token or not registration_token:
        raise HTTPException(401, "기존 계정과 새 Google 로그인이 모두 필요합니다.")
    try:
        source = await sessions.resolve_app_session(app_token)
        transfer = await invites.request_identity_transfer(
            source.account_id, target_registration_token=registration_token,
        )
    except (AuthSessionUnavailable, TransferUnavailable):
        raise HTTPException(409, "이 Google 계정으로 이전 요청을 만들 수 없습니다.") from None
    return {"transfer_id": transfer.transfer_id, "status": transfer.status}


@router.get("/me")
async def auth_me(request: Request):
    _require_google_mode()
    _, sessions, _, _ = await get_auth_services()
    app_token = request.cookies.get(APP_COOKIE)
    if app_token:
        try:
            account = await sessions.resolve_app_session(app_token)
            return {"state": "authenticated", "account_id": account.account_id, "role": account.role}
        except AuthSessionUnavailable:
            pass
    registration = request.cookies.get(REGISTRATION_COOKIE)
    if registration:
        try:
            identity = await sessions.resolve_registration_session(registration)
            return {"state": "invite_required", "email": identity.verified_email}
        except AuthSessionUnavailable:
            pass
    return {"state": "anonymous"}


@router.post("/logout", status_code=204)
async def logout(request: Request):
    _require_google_mode()
    _require_action(request, "logout")
    _, sessions, _, _ = await get_auth_services()
    token = request.cookies.get(APP_COOKIE)
    if token:
        await sessions.revoke_app_session(token)
    response = Response(status_code=204)
    response.delete_cookie(APP_COOKIE, path="/", samesite="lax")
    response.delete_cookie(REGISTRATION_COOKIE, path="/", samesite="lax")
    return response


def _require_google_mode() -> None:
    if get_settings().auth_mode != "google_invite":
        raise HTTPException(404, "Not found")


def _require_action(request: Request, action: str) -> None:
    settings = get_settings()
    origin = request.headers.get("origin")
    allowed = {value.strip() for value in settings.allowed_origins.split(",") if value.strip()}
    allowed.add(str(request.base_url).rstrip("/"))
    if (request.headers.get("x-auth-action") != action
            or request.headers.get("sec-fetch-site") == "cross-site"
            or origin is not None and origin not in allowed):
        raise HTTPException(403, "허용되지 않은 인증 요청입니다.")


def _set_cookie(response: Response, name: str, token: str, *, max_age: int) -> None:
    response.set_cookie(
        name, token, max_age=max_age, httponly=True,
        secure=get_settings().environment != "development", samesite="lax", path="/",
    )
