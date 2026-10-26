from __future__ import annotations

import pytest
from pydantic import ValidationError
from types import SimpleNamespace

from backend import main as app_main
from backend.shared.config import Settings


BASE = {
    "_env_file": None,
    "database_url": "postgresql://user:pass@127.0.0.1:55433/test",
    "environment": "development",
    "auth_mode": "google_invite",
    "google_client_id": "test-client",
    "google_client_secret": "test-secret",
    "google_redirect_uri": "http://localhost:8010/api/auth/google/callback",
    "auth_frontend_origin": "http://localhost:3110",
    "invite_code_pepper": "test-pepper-at-least-16-characters",
}


def test_explicit_login_test_mode_allows_missing_openrouter_key():
    settings = Settings(**BASE, login_test_mode=True, openrouter_api_key="")

    assert settings.login_test_mode is True
    assert settings.openrouter_api_key == ""


@pytest.mark.parametrize(
    "override",
    [
        {"auth_mode": "local"},
        {"environment": "production"},
    ],
)
def test_login_test_mode_is_restricted_to_local_google_invite_validation(override):
    with pytest.raises(ValidationError, match="LOGIN_TEST_MODE"):
        Settings(**(BASE | override), login_test_mode=True, openrouter_api_key="")


def test_health_distinguishes_login_only_mode(monkeypatch):
    monkeypatch.setattr(app_main, "settings", SimpleNamespace(login_test_mode=True))

    assert app_main.health() == {
        "status": "ok",
        "ai_status": "disabled_for_login_test",
    }
