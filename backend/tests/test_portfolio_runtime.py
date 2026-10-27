from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from starlette.requests import Request
from starlette.responses import Response

from backend.routes.agent import require_conversation_action
from backend.shared.config import Settings


PUBLIC_ORIGIN = "https://portfolio-demo.trycloudflare.com"
BASE = {
    "_env_file": None,
    "database_url": "postgresql://portfolio:synthetic@app-db:5432/portfolio",
    "runtime_mode": "anonymous_portfolio",
    "environment": "production",
    "auth_mode": "local",
    "llm_backend": "openrouter",
    "openrouter_api_key": "synthetic-key",
    "openrouter_base_url": "https://openrouter.ai/api/v1",
    "llm_model": "example/model:free",
    "worker_concurrency": 1,
    "allowed_origins": PUBLIC_ORIGIN,
    "portfolio_public_origin": PUBLIC_ORIGIN,
    "portfolio_evaluation_ends_at": "2099-01-01T00:00:00Z",
    "portfolio_free_model_allowlist": "example/model:free",
    "portfolio_daily_llm_call_limit": 40,
}


def test_portfolio_settings_accept_only_explicit_free_runtime():
    settings = Settings(**BASE)

    assert settings.is_portfolio is True
    assert settings.portfolio_free_models == ("example/model:free",)
    assert settings.portfolio_daily_llm_call_limit == 40


@pytest.mark.parametrize(
    "change, message",
    [
        ({"llm_backend": "codex-cli"}, "OpenRouter"),
        ({"openrouter_api_key": ""}, "API key"),
        ({"openrouter_base_url": "https://example.invalid/v1"}, "base URL"),
        ({"llm_model": "example/model"}, "free model"),
        ({"llm_model": "other/model:free"}, "allowlist"),
        ({"portfolio_free_model_allowlist": "example/model"}, "free model"),
        ({"worker_concurrency": 2}, "one worker"),
        ({"environment": "development"}, "production"),
        ({"auth_mode": "google_invite"}, "anonymous"),
        ({"langfuse_secret_key": "secret"}, "Langfuse"),
        ({"mcp_enabled": True, "mcp_base_url": "http://mcp:8001/mcp"}, "MCP"),
        ({"portfolio_public_origin": ""}, "public origin"),
        ({"portfolio_public_origin": "http://demo.test"}, "HTTPS"),
        ({"allowed_origins": PUBLIC_ORIGIN + ",https://other.test"}, "origin"),
        ({"portfolio_evaluation_ends_at": None}, "end time"),
        ({"portfolio_evaluation_ends_at": "2020-01-01T00:00:00Z"}, "future"),
        ({"portfolio_daily_llm_call_limit": 41}, "less than or equal to 40"),
    ],
)
def test_portfolio_settings_fail_closed(change, message):
    with pytest.raises((ValidationError, ValueError), match=message):
        Settings(**(BASE | change))


def _request(*, origin=PUBLIC_ORIGIN, action="agent-submit", method="POST"):
    headers = [(b"host", b"api:8000")]
    if origin is not None:
        headers.append((b"origin", origin.encode()))
    if action is not None:
        headers.append((b"x-conversation-action", action.encode()))
    return Request({
        "type": "http",
        "method": method,
        "path": "/api/agent",
        "headers": headers,
        "scheme": "http",
        "server": ("api", 8000),
        "client": ("172.20.0.3", 1234),
    })


def test_portfolio_mutation_requires_exact_public_origin_and_action(monkeypatch):
    settings = SimpleNamespace(
        is_portfolio=True,
        allowed_origins=PUBLIC_ORIGIN,
        portfolio_public_origin=PUBLIC_ORIGIN,
    )
    monkeypatch.setattr("backend.routes.agent.get_settings", lambda: settings)

    require_conversation_action(_request(), "agent-submit")
    for request in (
        _request(origin="https://evil.test"),
        _request(origin=None),
        _request(action=None),
        _request(action="wrong"),
    ):
        with pytest.raises(Exception) as error:
            require_conversation_action(request, "agent-submit")
        assert getattr(error.value, "status_code", None) == 403


def test_standard_settings_and_same_origin_action_contract_remain_compatible(monkeypatch):
    settings = Settings(
        _env_file=None,
        database_url="postgresql://u:p@localhost/db",
    )
    assert settings.is_portfolio is False

    monkeypatch.setattr("backend.routes.agent.get_settings", lambda: SimpleNamespace(
        is_portfolio=False,
        allowed_origins="http://localhost:3100",
    ))
    require_conversation_action(
        _request(origin="http://localhost:3100", action="delete"), "delete"
    )


def test_portfolio_end_time_is_timezone_aware():
    settings = Settings(**BASE)
    assert settings.portfolio_evaluation_ends_at > datetime.now(timezone.utc)


def test_portfolio_app_omits_auth_admin_and_api_documentation():
    env = os.environ.copy()
    env.update({
        "DATABASE_URL": BASE["database_url"],
        "RUNTIME_MODE": "anonymous_portfolio",
        "ENVIRONMENT": "production",
        "AUTH_MODE": "local",
        "LLM_BACKEND": "openrouter",
        "OPENROUTER_API_KEY": "synthetic-key",
        "OPENROUTER_BASE_URL": "https://openrouter.ai/api/v1",
        "LLM_MODEL": "example/model:free",
        "WORKER_CONCURRENCY": "1",
        "ALLOWED_ORIGINS": PUBLIC_ORIGIN,
        "PORTFOLIO_PUBLIC_ORIGIN": PUBLIC_ORIGIN,
        "PORTFOLIO_EVALUATION_ENDS_AT": "2099-01-01T00:00:00Z",
        "PORTFOLIO_FREE_MODEL_ALLOWLIST": "example/model:free",
        "PORTFOLIO_DAILY_LLM_CALL_LIMIT": "40",
        "LANGFUSE_PUBLIC_KEY": "",
        "LANGFUSE_SECRET_KEY": "",
        "MCP_ENABLED": "false",
        "MCP_BASE_URL": "",
    })
    result = subprocess.run(
        [sys.executable, "-c", (
            "import json; from backend.main import app; "
            "print(json.dumps(sorted({r.path for r in app.routes if hasattr(r, 'path')})))"
        )],
        cwd=Path(__file__).resolve().parents[2], env=env,
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20,
    )
    assert result.returncode == 0, result.stderr
    routes = json.loads(result.stdout.strip().splitlines()[-1])
    assert not any(path.startswith("/docs") for path in routes)
    assert "/openapi.json" not in routes
    assert not any(path.startswith("/api/auth") for path in routes)
    assert not any(path.startswith("/api/admin") for path in routes)


def test_portfolio_local_codex_profile_is_not_found(monkeypatch):
    from backend.routes.agent import local_profile

    monkeypatch.setattr("backend.routes.agent.get_settings", lambda: SimpleNamespace(
        is_portfolio=True,
        llm_backend="openrouter",
        local_profile_token="",
    ))
    request = _request(action="profile")
    response = Response()
    with pytest.raises(Exception) as error:
        import asyncio
        asyncio.run(local_profile(request, response))
    assert getattr(error.value, "status_code", None) == 404


def test_portfolio_runtime_closes_after_approved_end_time():
    from datetime import datetime, timezone

    settings = Settings(**BASE)
    assert not settings.portfolio_is_expired(
        now=datetime(2098, 12, 31, tzinfo=timezone.utc)
    )
    assert settings.portfolio_is_expired(
        now=datetime(2099, 1, 1, tzinfo=timezone.utc)
    )
