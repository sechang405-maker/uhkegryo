"""Distribution contract for the default Docker Compose stack."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[2]
CORE_SERVICES = {"app-db", "db-migrate", "api", "mcp", "searxng", "frontend"}
OBSERVABILITY_SERVICES = {
    "langfuse-web",
    "langfuse-worker",
    "langfuse-db",
    "clickhouse",
    "redis",
    "minio",
}


def compose_config(
    *, database_url: str | None = None, observability: bool = False,
    login_test_mode: bool = False,
) -> dict:
    cli = shutil.which("docker")
    if not cli:
        pytest.skip("Docker CLI required for Compose interpolation")

    env = {
        key: value
        for key, value in os.environ.items()
        if key
        not in {
            "COMPOSE_PROFILES",
            "DATABASE_URL",
            "OPENROUTER_API_KEY",
            "LANGFUSE_APP_URL",
            "LANGFUSE_PUBLIC_KEY",
            "LANGFUSE_SECRET_KEY",
        }
    }
    env["COMPOSE_PROJECT_NAME"] = "uhkegryo-compose-contract"
    if login_test_mode:
        env.update({"LOGIN_TEST_MODE": "1", "AUTH_MODE": "google_invite"})
    else:
        env["OPENROUTER_API_KEY"] = "test-openrouter-key"
    if database_url:
        env["DATABASE_URL"] = database_url

    command = [cli, "compose", "-f", str(ROOT / "docker-compose.yml")]
    if observability:
        command.extend(["--profile", "observability"])
    command.extend(["config", "--format", "json"])
    result = subprocess.run(
        command,
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_default_compose_is_a_complete_local_app_without_observability_secrets():
    config = compose_config()
    services = config["services"]

    assert set(services) == CORE_SERVICES
    assert services["app-db"]["healthcheck"]["test"][-1] == "pg_isready -U uhkegryo -d uhkegryo"
    assert services["db-migrate"]["command"] == ["python", "-m", "backend.db.run_migrations"]
    assert services["db-migrate"]["depends_on"]["app-db"]["condition"] == "service_healthy"
    assert services["api"]["depends_on"]["db-migrate"]["condition"] == "service_completed_successfully"
    assert services["api"]["environment"]["MCP_ENABLED"] == "true"
    assert services["api"]["environment"]["MCP_BASE_URL"] == "http://mcp:8001/mcp"
    assert services["api"]["environment"]["SEARXNG_BASE_URL"] == "http://searxng:8080"
    assert services["api"]["environment"]["INTERPRETER_PROMPT_PATH"] == (
        "/app/prompts/uhkegryo-interpreter-v4.md"
    )
    assert 'os.path.basename(path)' in "\n".join(services["api"]["command"])
    assert services["mcp"]["environment"]["DATABASE_URL"].startswith(
        "postgresql://uhkegryo:"
    )
    assert services["frontend"]["environment"]["AGENT_API_ORIGIN"] == "http://api:8000"
    assert services["frontend"]["depends_on"]["api"]["condition"] == "service_healthy"
    assert services["frontend"]["ports"][0]["host_ip"] == "127.0.0.1"
    assert Path(services["frontend"]["build"]["context"]).resolve() == ROOT.resolve()
    assert services["frontend"]["build"]["dockerfile"] == "frontend/Dockerfile"
    assert config["volumes"]["app_postgres_data"] is not None


def test_database_url_can_target_an_external_postgres_without_changing_images():
    external = "postgresql://reader:secret@db.example.test:5432/uhkegryo?sslmode=require"
    services = compose_config(database_url=external)["services"]

    assert services["db-migrate"]["environment"]["DATABASE_URL"] == external
    assert services["api"]["environment"]["DATABASE_URL"] == external


def test_observability_profile_is_opt_in_and_has_no_default_api_dependency():
    config = compose_config(observability=True)
    services = config["services"]

    assert set(services) == CORE_SERVICES | OBSERVABILITY_SERVICES
    for name in OBSERVABILITY_SERVICES:
        assert services[name]["profiles"] == ["observability"]
    assert "langfuse-web" not in services["api"]["depends_on"]


def test_login_test_mode_compose_parses_without_openrouter_key():
    services = compose_config(login_test_mode=True)["services"]

    assert services["api"]["environment"]["LOGIN_TEST_MODE"] == "1"
    assert services["api"]["environment"]["OPENROUTER_API_KEY"] == ""


def test_local_ollama_settings_are_value_safe_and_forwarded_without_credentials():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    sample = (ROOT / ".env.example").read_text(encoding="utf-8")
    guide = (ROOT / "docs/local-ollama.md").read_text(encoding="utf-8")

    assert "LLM_BACKEND: ${LLM_BACKEND:-openrouter}" in compose
    assert "OLLAMA_BASE_URL: ${OLLAMA_BASE_URL:-http://127.0.0.1:11434/v1}" in compose
    assert "OLLAMA_MODEL: ${OLLAMA_MODEL:-qwen3.5:4b-q4_K_M}" in compose
    assert "OLLAMA_API_KEY" not in compose
    assert "LLM_BACKEND=openrouter" in sample
    assert "OLLAMA_BASE_URL=http://127.0.0.1:11434/v1" in sample
    assert "OLLAMA_MODEL=qwen3.5:4b-q4_K_M" in sample
    assert "100% GPU" in guide
    assert "외부 터널" in guide
    assert "호스트에서" in guide

