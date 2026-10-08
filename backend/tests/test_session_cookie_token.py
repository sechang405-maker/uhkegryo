from backend.shared.auth import session_cookie_max_age
import hashlib
from types import SimpleNamespace

from fastapi import Response

from backend.shared.auth import create_session_token, hash_session_token, set_session_cookie


def test_create_session_token_returns_unique_opaque_tokens():
    first = create_session_token()
    second = create_session_token()

    assert first
    assert second
    assert first != second


def test_hash_session_token_uses_sha256_hex():
    token = "opaque-session-token"

    assert hash_session_token(token) == hashlib.sha256(token.encode("utf-8")).hexdigest()


def test_development_session_cookie_is_http_only_and_90_days():
    response = Response()
    settings = SimpleNamespace(environment="development")

    set_session_cookie(response, "opaque-token", settings)

    cookie = response.headers["set-cookie"]
    assert cookie.startswith("session_id=opaque-token;")
    assert f"Max-Age={session_cookie_max_age()}" in cookie
    assert "HttpOnly" in cookie
    assert "Path=/" in cookie
    assert "SameSite=lax" in cookie
    assert "Secure" not in cookie


def test_non_development_session_cookie_is_secure():
    response = Response()
    settings = SimpleNamespace(environment="production")

    set_session_cookie(response, "opaque-token", settings)

    assert "Secure" in response.headers["set-cookie"]
