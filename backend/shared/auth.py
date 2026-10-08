"""공통 인증: 익명 세션 쿠키와 세션 식별.
MCP 인증은 Cloud Run IAM으로 처리하므로 별도 JWT 불필요.
"""
import hashlib
import secrets
import calendar
from datetime import datetime, timezone

from fastapi import Cookie, HTTPException, Request, Response
from backend.shared.config import Settings

SESSION_COOKIE_NAME = "session_id"


def session_cookie_max_age(now: datetime | None = None) -> int:
    now = now or datetime.now(timezone.utc)
    year, month = divmod(now.year * 12 + now.month - 1 + 3, 12)
    month += 1
    expires = now.replace(year=year, month=month, day=min(now.day, calendar.monthrange(year, month)[1]))
    return int((expires - now).total_seconds())


def create_session_token() -> str:
    """브라우저 세션에 사용할 암호학적 무작위 토큰을 생성한다."""
    return secrets.token_urlsafe(32)


def hash_session_token(token: str) -> str:
    """저장소에 보관할 세션 토큰 SHA-256 hex digest를 반환한다."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def set_session_cookie(response: Response, token: str, settings: Settings) -> None:
    """환경별 보안 옵션을 적용해 달력 기준 3개월 익명 사용자 쿠키를 설정한다."""
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=session_cookie_max_age(),
        httponly=True,
        secure=settings.environment != "development",
        samesite="lax",
        path="/",
    )


def get_session_id(session_id: str | None = Cookie(default=None, alias="session_id")) -> str | None:
    """세션 쿠키에서 session_id 추출 (없으면 None)."""
    return session_id


async def get_current_user(request: Request) -> dict:
    """FastAPI 의존성: 세션 쿠키로 사용자 식별 (메인 API용)."""
    session_id = request.cookies.get("session_id")
    if session_id:
        return {"session_id": session_id, "source": "cookie"}
    raise HTTPException(status_code=401, detail="Authentication required")
