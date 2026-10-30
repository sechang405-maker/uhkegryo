from pathlib import Path
import subprocess

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


def test_vercel_hybrid_gateway_keeps_only_the_frontend_port_public():
    override = yaml.safe_load(
        (ROOT / "compose.portfolio-vercel.yml").read_text(encoding="utf-8")
    )
    assert set(override["services"]) == {"frontend"}
    frontend = override["services"]["frontend"]
    assert frontend["environment"]["PORTFOLIO_GATEWAY_REQUIRED"] == "1"
    assert "PORTFOLIO_GATEWAY_SECRET:?" in frontend["environment"]["PORTFOLIO_GATEWAY_SECRET"]
    assert "PORTFOLIO_GATEWAY_SECRET" in " ".join(frontend["healthcheck"]["test"])

    start = (ROOT / "scripts/portfolio-vercel-start.ps1").read_text(encoding="utf-8")
    stop = (ROOT / "scripts/portfolio-vercel-stop.ps1").read_text(encoding="utf-8")
    for script in (start, stop):
        assert "compose.portfolio.yml" in script
        assert "compose.portfolio-vercel.yml" in script
    assert "up --build" in start
    assert "down" in stop
    assert " down -v" not in stop and "--volumes" not in stop


def test_vercel_hybrid_examples_are_value_free_and_server_only():
    local_sample = (ROOT / ".env.portfolio.example").read_text(encoding="utf-8")
    vercel_sample = (ROOT / "frontend/vercel.env.example").read_text(encoding="utf-8")
    ignore = (ROOT / "frontend/.vercelignore").read_text(encoding="utf-8")

    assert "PORTFOLIO_GATEWAY_SECRET=" in local_sample
    assert "PORTFOLIO_GATEWAY_PROXY=1" in vercel_sample
    assert "PORTFOLIO_MODE=1" in vercel_sample
    assert "NEXT_PUBLIC_API_BASE_URL=/api" in vercel_sample
    assert "PORTFOLIO_GATEWAY_ORIGIN=" in vercel_sample
    assert "PORTFOLIO_GATEWAY_SECRET=" in vercel_sample
    assert "NEXT_PUBLIC_PORTFOLIO_GATEWAY" not in vercel_sample
    assert "OPENROUTER" not in vercel_sample
    assert "DATABASE" not in vercel_sample
    assert "tests/" in ignore and ".env*" in ignore


def test_windows_ollama_host_compose_exposes_only_isolated_loopback_dependencies():
    compose = yaml.safe_load(
        (ROOT / "compose.portfolio-ollama-host.yml").read_text(encoding="utf-8")
    )
    assert compose["name"] == "uhkegryo-portfolio-ollama-host"
    services = compose["services"]
    assert set(services) == {"db", "db-migrate", "searxng"}
    assert services["db"]["ports"] == [
        "127.0.0.1:${PORTFOLIO_DB_PORT:-55434}:5432"
    ]
    assert services["searxng"]["ports"] == [
        "127.0.0.1:${PORTFOLIO_SEARXNG_PORT:-8081}:8080"
    ]
    assert all(service.get("restart") == "no" for service in services.values())
    rendered = (ROOT / "compose.portfolio-ollama-host.yml").read_text(encoding="utf-8")
    assert "11434" not in rendered and "8000" not in rendered and "3120" not in rendered


def test_windows_ollama_host_scripts_are_explicit_nonpersistent_and_value_safe():
    generator = (ROOT / "scripts/portfolio-host-new-env.ps1").read_text(encoding="utf-8")
    start = (ROOT / "scripts/portfolio-host-start.ps1").read_text(encoding="utf-8")
    stop = (ROOT / "scripts/portfolio-host-stop.ps1").read_text(encoding="utf-8")
    tunnel = (ROOT / "scripts/portfolio-host-tunnel.ps1").read_text(encoding="utf-8")

    assert "RandomNumberGenerator" in generator
    assert "AddDays(7)" in generator
    assert "qwen3.5:4b-q4_K_M" in generator
    assert "OPENROUTER_API_KEY=" in generator
    assert "PORTFOLIO_GATEWAY_SECRET=" in generator
    assert "Write-Output" not in generator

    for source in (start, stop):
        assert "compose.portfolio-ollama-host.yml" in source
    assert "127.0.0.1" in start
    assert "PORTFOLIO_GATEWAY_REQUIRED" in start
    assert "Start-Process" in start and "-WindowStyle Hidden" in start
    assert "Set-Service" not in start and "New-Service" not in start
    assert " down -v" not in stop and "--volumes" not in stop
    assert "http://127.0.0.1:3120" in tunnel
    assert "--url" in tunnel


def test_windows_secret_primitives_run_on_the_supported_powershell():
    generator = (ROOT / "scripts/portfolio-host-new-env.ps1").read_text(encoding="utf-8")
    assert "RandomNumberGenerator]::Create()" in generator
    assert "BitConverter]::ToString" in generator
    assert "RandomNumberGenerator]::Fill" not in generator
    assert "Convert]::ToHexString" not in generator
    result = subprocess.run(
        [
            "powershell.exe", "-NoProfile", "-Command",
            "$b=[byte[]]::new(32);$g=[Security.Cryptography.RandomNumberGenerator]::Create();"
            "$g.GetBytes($b);$g.Dispose();(([BitConverter]::ToString($b)-replace '-','').Length)",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "64"
