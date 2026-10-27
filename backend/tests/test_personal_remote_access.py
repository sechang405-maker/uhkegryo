import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from starlette.requests import Request

from backend.shared.config import Settings


OWNER_ID = "11111111-1111-1111-1111-111111111111"
PUBLIC_ORIGIN = "https://owner-preview.vercel.app"
GATEWAY_ORIGIN = "https://owner-gateway.example"
SECRET = "synthetic-server-secret-" + "x" * 32

BASE = {
    "_env_file": None,
    "database_url": "postgresql://u:p@127.0.0.1:55433/uh",
    "runtime_mode": "personal_remote_test",
    "environment": "production",
    "auth_mode": "google_invite",
    "llm_backend": "codex-cli",
    "worker_concurrency": 1,
    "interpreter_prompt_version": "uhkegryo-interpreter-v4",
    "codex_owner_account_id": OWNER_ID,
    "google_client_id": "synthetic-client",
    "google_client_secret": "synthetic-client-secret",
    "google_redirect_uri": PUBLIC_ORIGIN + "/api/auth/google/callback",
    "auth_frontend_origin": PUBLIC_ORIGIN,
    "invite_code_pepper": "synthetic-pepper-long-enough",
    "allowed_origins": PUBLIC_ORIGIN,
    "personal_remote_public_origin": PUBLIC_ORIGIN,
    "personal_remote_gateway_origin": GATEWAY_ORIGIN,
    "personal_remote_gateway_secret": SECRET,
}


def _request(path="/api/agent", *, method="GET", host="owner-gateway.example",
             origin=PUBLIC_ORIGIN, secret=SECRET, site="same-origin"):
    headers = [(b"host", host.encode()), (b"x-personal-remote-gateway-secret", secret.encode())]
    if origin is not None:
        headers.append((b"origin", origin.encode()))
    if site is not None:
        headers.append((b"sec-fetch-site", site.encode()))
    return Request({
        "type": "http", "method": method, "path": path, "headers": headers,
        "scheme": "http", "server": ("127.0.0.1", 8010), "client": ("127.0.0.1", 40000),
    })


def _complete_immediate(coroutine):
    """Drive fakes that never suspend; avoids this host's broken Proactor socketpair."""
    with pytest.raises(StopIteration) as finished:
        coroutine.send(None)
    return finished.value.value


def test_personal_remote_settings_require_exact_isolated_boundary():
    settings = Settings(**BASE)
    assert settings.is_personal_remote_test
    assert settings.llm_model == "gpt-5.6-luna"

    invalid = (
        {"personal_remote_public_origin": ""},
        {"personal_remote_gateway_origin": "http://owner-gateway.example"},
        {"personal_remote_gateway_secret": "short"},
        {"personal_remote_gateway_secret": "é" * 40},
        {"personal_remote_gateway_secret": " " * 40},
        {"google_client_id": ""},
        {"google_client_secret": ""},
        {"invite_code_pepper": "short"},
        {"allowed_origins": PUBLIC_ORIGIN + ",https://evil.test"},
        {"auth_frontend_origin": "https://evil.test"},
        {"google_redirect_uri": PUBLIC_ORIGIN + "/wrong"},
        {"environment": "development"},
        {"auth_mode": "local"},
        {"llm_backend": "openrouter"},
        {"codex_owner_account_id": None},
        {"database_url": "postgresql://u:p@remote.invalid/uh"},
        {"worker_concurrency": 2},
        {"langfuse_secret_key": "synthetic"},
        {"mcp_enabled": True},
    )
    for change in invalid:
        with pytest.raises((ValidationError, ValueError)):
            Settings(**(BASE | change))


def test_gateway_policy_rejects_direct_tunnel_host_origin_csrf_and_secret_forgery():
    from backend.services.personal_remote_access import gateway_request_allowed

    settings = Settings(**BASE)
    assert gateway_request_allowed(settings, _request())
    assert gateway_request_allowed(
        settings, _request(path="/api/auth/google/callback", origin=None, site="cross-site")
    )
    for request in (
        _request(host="evil.test"),
        _request(secret="attacker-secret-" + "x" * 32),
        _request(secret="é"),
        _request(origin="https://evil.test"),
        _request(method="POST", origin=None),
        _request(method="POST", site="cross-site"),
    ):
        assert not gateway_request_allowed(settings, request)


def test_only_login_start_and_callback_are_session_exceptions():
    from backend.services.personal_remote_access import is_login_exception

    assert is_login_exception("/api/auth/google/start")
    assert is_login_exception("/api/auth/google/callback")
    for path in ("/api/auth/me", "/api/auth/logout", "/api/auth/invite/redeem", "/api/agent"):
        assert not is_login_exception(path)


def test_owner_policy_rejects_other_admin_unregistered_disabled_and_expired_session():
    from backend.services.personal_remote_access import owner_account_allowed

    settings = Settings(**BASE)
    assert owner_account_allowed(settings, SimpleNamespace(
        account_id=OWNER_ID, role="admin", status="active",
    ))
    for account in (
        None,
        SimpleNamespace(account_id="22222222-2222-2222-2222-222222222222", role="admin", status="active"),
        SimpleNamespace(account_id=OWNER_ID, role="user", status="active"),
        SimpleNamespace(account_id=OWNER_ID, role="admin", status="disabled"),
    ):
        assert not owner_account_allowed(settings, account)
    assert not owner_account_allowed(
        SimpleNamespace(is_personal_remote_test=True, codex_owner_account_id=None),
        SimpleNamespace(account_id=OWNER_ID, role="admin", status="active"),
    )


def test_public_portfolio_never_uses_personal_remote_gateway_policy():
    from backend.services.personal_remote_access import gateway_request_allowed

    portfolio = SimpleNamespace(is_personal_remote_test=False)
    assert not gateway_request_allowed(portfolio, _request())


def test_personal_gateway_middleware_requires_gateway_and_owner_session(monkeypatch):
    import backend.main as main
    from backend.services.auth_session_repository import AuthSessionUnavailable

    settings = Settings(**BASE)
    monkeypatch.setattr(main, "settings", settings)

    class Sessions:
        account = None

        async def resolve_app_session(self, token):
            if token == "expired":
                raise AuthSessionUnavailable
            return self.account

    sessions = Sessions()

    async def services():
        return None, sessions, None, None

    monkeypatch.setattr("backend.routes.auth.get_auth_services", services)

    called = []

    async def next_handler(request):
        called.append(request)
        return SimpleNamespace(status_code=200)

    def scenario():
        missing = _complete_immediate(main.personal_remote_guard(
            _request(secret=""), next_handler,
        ))
        assert missing.status_code == 404 and called == []

        login = _complete_immediate(main.personal_remote_guard(
            _request(path="/api/auth/google/start", origin=None), next_handler,
        ))
        assert login.status_code == 200

        unauthenticated = _complete_immediate(main.personal_remote_guard(_request(), next_handler))
        assert unauthenticated.status_code == 401

        expired = _request()
        expired._cookies = {"session_id": "expired"}
        assert _complete_immediate(main.personal_remote_guard(expired, next_handler)).status_code == 401

        sessions.account = SimpleNamespace(
            account_id="22222222-2222-2222-2222-222222222222", role="admin", status="active"
        )
        wrong = _request()
        wrong._cookies = {"session_id": "valid"}
        assert _complete_immediate(main.personal_remote_guard(wrong, next_handler)).status_code == 403

        sessions.account = SimpleNamespace(account_id=OWNER_ID, role="admin", status="active")
        owner = _request()
        owner._cookies = {"session_id": "valid"}
        assert _complete_immediate(main.personal_remote_guard(owner, next_handler)).status_code == 200
        assert owner.state.account.account_id == OWNER_ID

    scenario()


def test_personal_app_exposes_only_minimal_auth_routes_and_no_admin_surface():
    env = os.environ.copy()
    env.update({
        "DATABASE_URL": BASE["database_url"],
        "RUNTIME_MODE": BASE["runtime_mode"],
        "ENVIRONMENT": BASE["environment"],
        "AUTH_MODE": BASE["auth_mode"],
        "LLM_BACKEND": BASE["llm_backend"],
        "WORKER_CONCURRENCY": "1",
        "INTERPRETER_PROMPT_VERSION": BASE["interpreter_prompt_version"],
        "CODEX_OWNER_ACCOUNT_ID": OWNER_ID,
        "GOOGLE_CLIENT_ID": BASE["google_client_id"],
        "GOOGLE_CLIENT_SECRET": BASE["google_client_secret"],
        "GOOGLE_REDIRECT_URI": BASE["google_redirect_uri"],
        "AUTH_FRONTEND_ORIGIN": PUBLIC_ORIGIN,
        "INVITE_CODE_PEPPER": BASE["invite_code_pepper"],
        "ALLOWED_ORIGINS": PUBLIC_ORIGIN,
        "PERSONAL_REMOTE_PUBLIC_ORIGIN": PUBLIC_ORIGIN,
        "PERSONAL_REMOTE_GATEWAY_ORIGIN": GATEWAY_ORIGIN,
        "PERSONAL_REMOTE_GATEWAY_SECRET": SECRET,
        "LANGFUSE_PUBLIC_KEY": "", "LANGFUSE_SECRET_KEY": "",
        "MCP_ENABLED": "false", "MCP_BASE_URL": "",
    })
    result = subprocess.run(
        [sys.executable, "-c", (
            "import json\nfrom backend.main import app\n"
            "def walk(routes):\n"
            " out=[]\n"
            " for route in routes:\n"
            "  path=getattr(route,'path',None)\n"
            "  if path: out.append(path)\n"
            "  nested=getattr(route,'original_router',None)\n"
            "  if nested is not None: out.extend(walk(nested.routes))\n"
            " return out\n"
            "print(json.dumps(sorted(set(walk(app.routes)))))"
        )],
        cwd=Path(__file__).resolve().parents[2], env=env,
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20,
    )
    assert result.returncode == 0, result.stderr
    routes = json.loads(result.stdout.strip().splitlines()[-1])
    assert set(path for path in routes if path.startswith("/api/auth/")) == {
        "/api/auth/google/start", "/api/auth/google/callback", "/api/auth/me", "/api/auth/logout",
    }
    assert not any(path.startswith("/api/admin") for path in routes)
    assert "/openapi.json" not in routes
    assert not any(path.startswith("/docs") for path in routes)


def test_personal_callback_refuses_unregistered_other_or_inactive_accounts():
    from backend.routes.auth import personal_callback_account_allowed

    settings = Settings(**BASE)
    assert personal_callback_account_allowed(settings, SimpleNamespace(
        account_id=OWNER_ID, role="admin", status="active"
    ))
    for account in (
        None,
        SimpleNamespace(account_id="22222222-2222-2222-2222-222222222222", role="admin", status="active"),
        SimpleNamespace(account_id=OWNER_ID, role="admin", status="disabled"),
    ):
        assert not personal_callback_account_allowed(settings, account)


def test_personal_callback_never_creates_registration_or_invite_session(monkeypatch):
    from backend.routes import auth

    settings = Settings(**BASE)
    registration_created = False

    class Accounts:
        async def get_by_google_subject(self, subject):
            return None

        async def record_google_login(self, subject, **identity):
            return None

    class Sessions:
        async def create_registration_session(self, **identity):
            nonlocal registration_created
            registration_created = True
            return "must-not-exist"

    class OIDC:
        async def verify_callback(self, **params):
            return SimpleNamespace(
                google_subject="unregistered", verified_email="nobody@example.test", display_name="Nobody"
            )

    async def services():
        return Accounts(), Sessions(), None, OIDC()

    monkeypatch.setattr(auth, "get_auth_services", services)
    monkeypatch.setattr(auth, "get_settings", lambda: settings)
    with pytest.raises(Exception) as error:
        _complete_immediate(auth.google_callback(_request(
            path="/api/auth/google/callback", origin=None,
        ), state="state", code="code"))
    assert getattr(error.value, "status_code", None) == 403
    assert registration_created is False


def test_personal_login_start_and_owner_callback_complete_without_invite_flow(monkeypatch):
    from backend.routes import auth

    settings = Settings(**BASE)
    owner = SimpleNamespace(account_id=OWNER_ID, role="admin", status="active")
    registration_created = False

    class Accounts:
        async def get_by_google_subject(self, subject):
            return owner

        async def record_google_login(self, subject, **identity):
            return owner

    class Sessions:
        async def create_app_session(self, account_id):
            assert account_id == OWNER_ID
            return "synthetic-owner-session"

        async def create_registration_session(self, **identity):
            nonlocal registration_created
            registration_created = True
            return "must-not-exist"

    class OIDC:
        async def authorization_url(self):
            return "https://accounts.google.com/o/oauth2/v2/auth?state=synthetic"

        async def verify_callback(self, **params):
            return SimpleNamespace(
                google_subject="owner-google", verified_email="owner@example.test", display_name="Owner"
            )

    async def services():
        return Accounts(), Sessions(), None, OIDC()

    monkeypatch.setattr(auth, "get_auth_services", services)
    monkeypatch.setattr(auth, "get_settings", lambda: settings)

    start = _complete_immediate(auth.google_start())
    assert start.status_code == 307
    assert start.headers["location"].startswith("https://accounts.google.com/")

    callback = _complete_immediate(auth.google_callback(_request(
        path="/api/auth/google/callback", origin=None,
    ), state="state", code="code"))
    assert callback.status_code == 307
    assert callback.headers["location"] == PUBLIC_ORIGIN + "/"
    cookie = callback.headers["set-cookie"]
    assert "session_id=synthetic-owner-session" in cookie
    assert "HttpOnly" in cookie and "Secure" in cookie and "SameSite=lax" in cookie
    assert registration_created is False
