param([string]$EnvFile = ".env.portfolio.local")

$ErrorActionPreference = "Stop"
$repositoryRoot = Split-Path -Parent $PSScriptRoot
$composeFile = Join-Path $repositoryRoot "compose.portfolio-ollama-host.yml"
$envPath = if ([IO.Path]::IsPathRooted($EnvFile)) { $EnvFile } else { Join-Path $repositoryRoot $EnvFile }
$runDir = Join-Path $repositoryRoot ".local-run\portfolio-host"
$pidFile = Join-Path $runDir "pids.json"
if (-not (Test-Path -LiteralPath $envPath -PathType Leaf)) { throw "Portfolio secret environment is missing." }
if (Test-Path -LiteralPath $pidFile) { throw "Portfolio PID record already exists. Stop or inspect the existing runtime first." }

foreach ($line in [IO.File]::ReadAllLines($envPath)) {
    if (-not $line -or $line.StartsWith("#")) { continue }
    $parts = $line.Split("=", 2)
    if ($parts.Count -ne 2 -or $parts[0] -notmatch '^[A-Z0-9_]+$') { throw "Invalid portfolio environment entry." }
    [Environment]::SetEnvironmentVariable($parts[0], $parts[1], "Process")
}

foreach ($name in @("PORTFOLIO_POSTGRES_PASSWORD", "PORTFOLIO_SEARXNG_SECRET", "PORTFOLIO_GATEWAY_SECRET", "PORTFOLIO_EVALUATION_ENDS_AT", "PORTFOLIO_PUBLIC_ORIGIN")) {
    if ([string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($name, "Process"))) { throw "Required portfolio setting is missing: $name" }
}
if ($env:PORTFOLIO_GATEWAY_SECRET.Length -lt 64) { throw "Gateway secret is too short." }
if ([DateTimeOffset]::Parse($env:PORTFOLIO_EVALUATION_ENDS_AT) -le [DateTimeOffset]::UtcNow) { throw "Portfolio evaluation window has expired." }

function Assert-PortFree([int]$port) {
    $listener = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, $port)
    try { $listener.Start() } catch { throw "Loopback port $port is already in use." } finally { try { $listener.Stop() } catch {} }
}
foreach ($port in @([int]$env:PORTFOLIO_DB_PORT, [int]$env:PORTFOLIO_SEARXNG_PORT, [int]$env:PORTFOLIO_API_PORT, [int]$env:PORTFOLIO_FRONTEND_PORT)) { Assert-PortFree $port }

$modelList = & ollama list
if ($LASTEXITCODE -ne 0 -or ($modelList -join "`n") -notmatch '^qwen3\.5:4b-q4_K_M\s') { throw "Approved Ollama model is not installed." }

New-Item -ItemType Directory -Path $runDir -Force | Out-Null
docker compose --env-file $envPath -f $composeFile up -d --build --wait db searxng
if ($LASTEXITCODE -ne 0) { throw "Isolated database/search startup failed." }
docker compose --env-file $envPath -f $composeFile run --rm db-migrate
if ($LASTEXITCODE -ne 0) { throw "Isolated database migration failed." }

$env:DATABASE_URL = "postgresql://portfolio:$($env:PORTFOLIO_POSTGRES_PASSWORD)@127.0.0.1:$($env:PORTFOLIO_DB_PORT)/portfolio"
$env:RUNTIME_MODE = "anonymous_portfolio"
$env:ENVIRONMENT = "production"
$env:AUTH_MODE = "local"
$env:WORKER_CONCURRENCY = "1"
$env:LLM_TIMEOUT_SECONDS = "90"
$env:PORTFOLIO_DAILY_LLM_CALL_LIMIT = "40"
$env:PORTFOLIO_MAX_PENDING_JOBS = "8"
$env:PORTFOLIO_DAILY_TERM_SEARCH_LIMIT = "80"
$env:ALLOWED_ORIGINS = $env:PORTFOLIO_PUBLIC_ORIGIN
$env:SEARXNG_BASE_URL = "http://127.0.0.1:$($env:PORTFOLIO_SEARXNG_PORT)"
$env:TERM_CARDS_PATH = Join-Path $repositoryRoot "docs\domains\illustration-reference\term-cards"
$env:STRUCTURED_OUTPUT_SKILL_PATH = Join-Path $repositoryRoot "skills\structured-output\SKILL.md"
$env:INTERPRETER_PROMPT_PATH = Join-Path $repositoryRoot "prompts\uhkegryo-interpreter-v4.md"
$env:INTERPRETER_PROMPT_VERSION = "uhkegryo-interpreter-v4"
$env:MCP_ENABLED = "false"
$env:MCP_BASE_URL = ""
$env:LANGFUSE_PUBLIC_KEY = ""
$env:LANGFUSE_SECRET_KEY = ""
$env:PORTFOLIO_GATEWAY_REQUIRED = "1"
$env:PORTFOLIO_MODE = "1"
$env:NEXT_PUBLIC_PORTFOLIO_MODE = "1"
$env:NEXT_PUBLIC_API_BASE_URL = "/api"
$env:NEXT_PUBLIC_UI_DEMO = "0"
$env:AGENT_API_ORIGIN = "http://127.0.0.1:$($env:PORTFOLIO_API_PORT)"

& npm.cmd run build --prefix frontend
if ($LASTEXITCODE -ne 0) { throw "Portfolio frontend build failed." }

$python = Join-Path $repositoryRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) { throw "Repository Python environment is missing." }
$apiOut = Join-Path $runDir "api.out.log"
$apiErr = Join-Path $runDir "api.err.log"
$webOut = Join-Path $runDir "web.out.log"
$webErr = Join-Path $runDir "web.err.log"
$api = Start-Process -FilePath $python -ArgumentList @("-m", "uvicorn", "backend.main:app", "--host", "127.0.0.1", "--port", $env:PORTFOLIO_API_PORT, "--no-access-log") -WorkingDirectory $repositoryRoot -WindowStyle Hidden -RedirectStandardOutput $apiOut -RedirectStandardError $apiErr -PassThru
$web = Start-Process -FilePath "npm.cmd" -ArgumentList @("run", "start", "--prefix", "frontend", "--", "--hostname", "127.0.0.1", "--port", $env:PORTFOLIO_FRONTEND_PORT) -WorkingDirectory $repositoryRoot -WindowStyle Hidden -RedirectStandardOutput $webOut -RedirectStandardError $webErr -PassThru

$records = @(
    @{ name = "api"; id = $api.Id; started_ticks = $api.StartTime.ToUniversalTime().Ticks },
    @{ name = "web"; id = $web.Id; started_ticks = $web.StartTime.ToUniversalTime().Ticks }
)
[IO.File]::WriteAllText($pidFile, ($records | ConvertTo-Json), [Text.UTF8Encoding]::new($false))

try {
    $ready = $false
    for ($attempt = 0; $attempt -lt 60; $attempt++) {
        Start-Sleep -Seconds 1
        try {
            $response = Invoke-WebRequest -UseBasicParsing -TimeoutSec 3 -Headers @{ "x-portfolio-gateway-secret" = $env:PORTFOLIO_GATEWAY_SECRET } -Uri "http://127.0.0.1:$($env:PORTFOLIO_FRONTEND_PORT)/service-health"
            if ($response.StatusCode -eq 200) { $ready = $true; break }
        } catch {}
    }
    if (-not $ready) { throw "Protected local gateway did not become healthy." }
} catch {
    & (Join-Path $PSScriptRoot "portfolio-host-stop.ps1") -EnvFile $envPath
    throw
}
