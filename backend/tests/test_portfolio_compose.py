from pathlib import Path
import shutil
import subprocess

import pytest
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
    assert '"PORTFOLIO_EVALUATION_ENDS_AT=disabled"' in generator
    assert "AddDays(7)" not in generator
    assert "qwen3.5:4b-q4_K_M" in generator
    assert "OPENROUTER_API_KEY=" in generator
    assert "PORTFOLIO_GATEWAY_SECRET=" in generator
    assert "Write-Output" not in generator

    for source in (start, stop):
        assert "compose.portfolio-ollama-host.yml" in source
    assert "127.0.0.1" in start
    assert "ollama show qwen3.5:4b-q4_K_M" in start
    assert "ollama list" not in start
    assert "PORTFOLIO_GATEWAY_REQUIRED" in start
    assert '$env:PORTFOLIO_EVALUATION_ENDS_AT -ne "disabled"' in start
    assert "Start-Process" in start and "-WindowStyle Hidden" in start
    assert "Get-NetTCPConnection" in start
    assert "owning_process" in start
    assert "Set-Service" not in start and "New-Service" not in start
    assert " down -v" not in stop and "--volumes" not in stop
    assert "http://127.0.0.1:3120" in tunnel
    assert "--url" in tunnel
    assert "Get-Command" in tunnel
    assert "Program Files (x86)\\cloudflared\\cloudflared.exe" in tunnel
    assert tunnel.index("Remove-Item -LiteralPath $logFile") < tunnel.index("Start-Process")
    assert tunnel.index("Remove-Item -LiteralPath $originFile") < tunnel.index("Start-Process")


def test_windows_one_click_entrypoints_preserve_runtime_security_boundaries():
    online = (ROOT / "scripts/portfolio-host-online.ps1").read_text(encoding="utf-8")
    admin_db = (ROOT / "scripts/portfolio-admin-db.ps1").read_text(encoding="utf-8")
    stop = (ROOT / "scripts/portfolio-host-stop.ps1").read_text(encoding="utf-8")
    start_cmd = (ROOT / "어케그려-서비스-실행.cmd").read_text(encoding="utf-8")
    stop_cmd = (ROOT / "어케그려-서비스-종료.cmd").read_text(encoding="utf-8")
    guide = (ROOT / "어케그려-서비스-실행-안내.md").read_text(encoding="utf-8")

    assert "portfolio-host-start.ps1" in online
    assert "portfolio-host-stop.ps1" in online
    assert "portfolio-host-tunnel.ps1" in online
    assert "portfolio-admin-db.ps1" in online
    assert "portfolio-admin-db.ps1" in stop
    assert "Test-TrackedProcess" in online
    assert "$parsedRecords | ForEach-Object { $_ }" in online
    assert "started_ticks" in online
    assert "PORTFOLIO_GATEWAY_ORIGIN" in online
    assert "SkipVercelUpdate" in online
    assert '$vercelVersion = "50.6.1"' in online
    assert '"vercel@$vercelVersion"' in online
    assert "--target production" in online
    assert "--sensitive" in online
    assert "RedirectStandardInput" in online
    assert "vercel-origin-input.tmp" in online
    assert "https://uhkegryo-xi.vercel.app/service-health" not in online
    assert '"$publicOrigin/service-health"' in online
    assert "New-Service" not in online and "Set-Service" not in online
    assert "New-NetFirewallRule" not in online
    assert "portfolio-host-new-env.ps1" not in online
    assert "PORTFOLIO_GATEWAY_SECRET=" not in online

    assert '"uhkegryo-oauth-local-app-db-1"' in admin_db
    assert '"uhkegryo-oauth-local"' in admin_db
    assert '"app-db"' in admin_db
    assert '"55433"' in admin_db
    assert '"127.0.0.1"' in admin_db
    assert '"/var/lib/postgresql/data"' in admin_db
    assert "docker start" in admin_db and "docker stop" in admin_db
    assert "docker compose" not in admin_db
    assert "docker rm" not in admin_db
    assert "New-Service" not in admin_db and "Set-Service" not in admin_db

    assert "portfolio-host-online.ps1" in start_cmd
    assert "portfolio-host-stop.ps1" in stop_cmd
    assert "pause" in start_cmd and "pause" in stop_cmd
    assert "Docker Desktop" in guide
    assert "PORTFOLIO_GATEWAY_ORIGIN" in guide
    assert "기존 관리자 DB" in guide
    assert "portfolio-host-new-env.ps1" in guide
    assert "자동 부팅" in guide


@pytest.mark.skipif(shutil.which("powershell.exe") is None, reason="Windows PowerShell runtime check")
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
