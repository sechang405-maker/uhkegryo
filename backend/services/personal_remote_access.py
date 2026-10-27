"""Fail-closed policy for the isolated owner-only remote test path."""

from __future__ import annotations

import secrets
from urllib.parse import urlsplit


LOGIN_EXCEPTIONS = frozenset({
    "/api/auth/google/start",
    "/api/auth/google/callback",
})
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def is_login_exception(path: str) -> bool:
    return path in LOGIN_EXCEPTIONS


def owner_account_allowed(settings, account) -> bool:
    owner_account_id = getattr(settings, "codex_owner_account_id", None)
    return bool(
        getattr(settings, "is_personal_remote_test", False)
        and owner_account_id is not None
        and account is not None
        and str(getattr(account, "account_id", ""))
        == str(owner_account_id)
        and getattr(account, "role", None) == "admin"
        and getattr(account, "status", None) == "active"
    )


def gateway_request_allowed(settings, request) -> bool:
    if not getattr(settings, "is_personal_remote_test", False):
        return False
    expected_secret = getattr(settings, "personal_remote_gateway_secret", "")
    supplied_secret = request.headers.get("x-personal-remote-gateway-secret", "")
    if len(expected_secret) < 32 or not secrets.compare_digest(
        supplied_secret.encode("utf-8"), expected_secret.encode("utf-8")
    ):
        return False
    gateway = urlsplit(getattr(settings, "personal_remote_gateway_origin", ""))
    try:
        expected_host = gateway.hostname
        if gateway.port is not None:
            expected_host = f"{expected_host}:{gateway.port}"
    except ValueError:
        return False
    if request.headers.get("host", "").casefold() != str(expected_host).casefold():
        return False
    origin = request.headers.get("origin")
    public = getattr(settings, "personal_remote_public_origin", "").rstrip("/")
    if origin is not None and origin.rstrip("/") != public:
        return False
    if request.method.upper() not in SAFE_METHODS and origin is None:
        return False
    if request.headers.get("sec-fetch-site", "").casefold() == "cross-site" and not is_login_exception(request.url.path):
        return False
    return True
