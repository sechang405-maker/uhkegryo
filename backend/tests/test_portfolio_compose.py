from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]


def test_portfolio_compose_is_standalone_loopback_only_and_never_restarts():
    compose = yaml.safe_load((ROOT / "compose.portfolio.yml").read_text(encoding="utf-8"))
    assert compose["name"] == "uhkegryo-portfolio"
    services = compose["services"]
    assert set(services) == {"db", "db-migrate", "searxng", "api", "frontend"}
    assert services["frontend"]["ports"] == [
        "127.0.0.1:${PORTFOLIO_FRONTEND_PORT:-3120}:3000"
    ]
    assert all("ports" not in services[name] for name in ("db", "db-migrate", "searxng", "api"))
    assert all(service.get("restart") == "no" for service in services.values())
    assert services["api"]["environment"]["RUNTIME_MODE"] == "anonymous_portfolio"
    assert services["api"]["environment"]["WORKER_CONCURRENCY"] == "1"
    assert services["api"]["environment"]["MCP_ENABLED"] == "false"
    assert services["api"]["environment"]["LANGFUSE_PUBLIC_KEY"] == ""
    assert services["api"]["environment"]["LANGFUSE_SECRET_KEY"] == ""
    assert services["api"]["environment"]["SEARXNG_BASE_URL"] == "http://searxng:8080"
    assert services["api"]["environment"]["PORTFOLIO_MODEL_CATALOG_PATH"] == (
        "/run/portfolio/openrouter-models.json"
    )
    assert services["api"]["volumes"] == [{
        "type": "bind",
        "source": (
            "${PORTFOLIO_MODEL_CATALOG_FILE:?Set the approved fresh "
            "OpenRouter models response file}"
        ),
        "target": "/run/portfolio/openrouter-models.json",
        "read_only": True,
    }]
    assert "--no-access-log" in services["api"]["command"]


def test_portfolio_lifecycle_is_explicit_and_stop_preserves_database_volume():
    start = (ROOT / "scripts/portfolio-start.ps1").read_text(encoding="utf-8")
    stop = (ROOT / "scripts/portfolio-stop.ps1").read_text(encoding="utf-8")
    sample = (ROOT / ".env.portfolio.example").read_text(encoding="utf-8")

    assert "docker compose" in start and "up --build" in start
    assert "docker compose" in stop and "down" in stop
    assert " down -v" not in stop and "--volumes" not in stop
    assert "PORTFOLIO_EVALUATION_ENDS_AT=" in sample
    assert "PORTFOLIO_PUBLIC_ORIGIN=" in sample
    assert "PORTFOLIO_OPENROUTER_API_KEY=" in sample
    assert "PORTFOLIO_FREE_MODEL_ALLOWLIST=" in sample
    assert "PORTFOLIO_MODEL_CATALOG_FILE=" in sample
    assert "PORTFOLIO_OPENROUTER_API_KEY:?" in (ROOT / "compose.portfolio.yml").read_text(encoding="utf-8")
