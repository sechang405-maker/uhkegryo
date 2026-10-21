param(
    [string]$Python = 'python',
    [string]$SearchUrl = 'http://127.0.0.1:8080',
    [string]$SearchContainer = 'uhkegryo-local-searxng'
)
$ErrorActionPreference = 'Stop'
$repository = Split-Path -Parent $PSScriptRoot
$frontend = Join-Path $repository 'frontend'
$logs = Join-Path $repository '.local-run'
$nextCli = Join-Path $frontend 'node_modules/next/dist/bin/next'
foreach ($required in @('.env.local-codex', '.env.local-profile', 'frontend/.next/BUILD_ID')) {
    if (-not (Test-Path -LiteralPath (Join-Path $repository $required))) {
        throw "Missing $required. Follow docs/local-codex.md before starting."
    }
}
$pythonExe = (Get-Command $Python -ErrorAction Stop).Source
$nodeExe = (Get-Command node -ErrorAction Stop).Source
if (-not (Test-Path -LiteralPath $nextCli)) { throw 'Frontend dependencies are missing.' }
New-Item -ItemType Directory -Force -Path $logs | Out-Null

function Get-Listener($Port) {
    Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue
}
function Wait-Http($Url) {
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        try {
            $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 2
            if ($response.StatusCode -eq 200) { return }
        } catch { }
        Start-Sleep -Seconds 1
    }
    throw "Not ready: $Url. Inspect logs in $logs; started processes are preserved."
}

# Reuse the existing personal container and volume. Never create or migrate a DB.
$dbState = & docker inspect --format '{{.State.Running}}' uhkegryo-local-codex-db-1 2>$null
if ($LASTEXITCODE -ne 0) { throw 'Existing personal DB container is unavailable. Start Docker Desktop and check docs/local-codex.md.' }
if ($dbState -ne 'true') {
    & docker start uhkegryo-local-codex-db-1 | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Could not start the existing personal DB container.' }
}
for ($attempt = 0; $attempt -lt 30; $attempt++) {
    $dbHealth = & docker inspect --format '{{.State.Health.Status}}' uhkegryo-local-codex-db-1 2>$null
    if ($dbHealth -eq 'healthy') { break }
    Start-Sleep -Seconds 1
}
if ($dbHealth -ne 'healthy') { throw 'Personal DB did not become healthy; API was not started.' }

# Reuse the dedicated patched search container; never auto-create containers or secrets.
if ($SearchUrl) {
    $searchOrigin = [uri]$SearchUrl
    if ($searchOrigin.Scheme -ne 'http' -or $searchOrigin.Host -notin @('127.0.0.1', 'localhost', '[::1]') -or
        $searchOrigin.UserInfo -or $searchOrigin.AbsolutePath -ne '/' -or $searchOrigin.Query -or $searchOrigin.Fragment) {
        throw 'SearchUrl must be a loopback HTTP origin.'
    }
    if ($SearchContainer -and -not (Get-Listener $searchOrigin.Port)) {
        & docker start $SearchContainer | Out-Null
        if ($LASTEXITCODE -ne 0) { throw 'Existing search container is unavailable. See docs/local-codex.md.' }
    }
    Wait-Http $SearchUrl
}

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss-fff'
if (-not (Get-Listener 8000)) {
    # Windows Start-Process creates a detached process; do not use -Wait or a tool-owned foreground session.
    $apiArguments = @('-m', 'backend.local_codex', '--local-settings')
    if ($SearchUrl) { $apiArguments += @('--search-url', $SearchUrl) }
    $api = Start-Process -FilePath $pythonExe -ArgumentList $apiArguments `
        -WorkingDirectory $repository -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $logs "api-$stamp.out.log") `
        -RedirectStandardError (Join-Path $logs "api-$stamp.err.log")
    Write-Output "API launched: PID $($api.Id)"
}
Wait-Http 'http://127.0.0.1:8000/health'
if (-not (Get-Listener 3100)) {
    $savedOrigin = $env:AGENT_API_ORIGIN
    $savedDemo = $env:NEXT_PUBLIC_UI_DEMO
    try {
        $env:AGENT_API_ORIGIN = 'http://127.0.0.1:8000'
        $env:NEXT_PUBLIC_UI_DEMO = '0'
        $ui = Start-Process -FilePath $nodeExe -ArgumentList ('"{0}" start -p 3100 -H 127.0.0.1' -f $nextCli) `
            -WorkingDirectory $frontend -WindowStyle Hidden -PassThru `
            -RedirectStandardOutput (Join-Path $logs "frontend-$stamp.out.log") `
            -RedirectStandardError (Join-Path $logs "frontend-$stamp.err.log")
        Write-Output "Frontend launched: PID $($ui.Id)"
    } finally {
        $env:AGENT_API_ORIGIN = $savedOrigin
        $env:NEXT_PUBLIC_UI_DEMO = $savedDemo
    }
}
Wait-Http 'http://127.0.0.1:3100/'
Wait-Http 'http://127.0.0.1:3100/service-health'
Write-Output 'Ready: http://127.0.0.1:3100 (API and frontend proxy health OK). No generation request was sent.'
Write-Output "Logs: $logs"
