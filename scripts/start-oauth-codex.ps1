param(
    [string]$Python = '',
    [string]$SettingsPath = '',
    [string]$CodexBinDir = '',
    [int]$DatabasePort = 55433,
    [int]$ApiPort = 8010,
    [int]$FrontendPort = 3110,
    [string]$SearchUrl = 'http://127.0.0.1:8081'
)
$ErrorActionPreference = 'Stop'
$repository = Split-Path -Parent $PSScriptRoot
$frontend = Join-Path $repository 'frontend'
$logs = Join-Path $repository '.local-run'
$compose = Join-Path $repository 'docker-compose.yml'
$override = Join-Path $repository 'compose.oauth-host.yml'
$nextCli = Join-Path $frontend 'node_modules/next/dist/bin/next'
if (-not $Python) { $Python = Join-Path $repository '.venv/Scripts/python.exe' }
if (-not $SettingsPath) {
    $SettingsPath = Join-Path $env:USERPROFILE 'AppData/Local/Packages/OpenAI.Codex_2p2nqsd0c76g0/LocalCache/Local/uhkegryo/oauth-local.env'
}
if (-not $CodexBinDir) {
    $CodexBinDir = Join-Path $env:USERPROFILE 'AppData/Local/OpenAI/Codex/bin'
}

foreach ($required in @(
    $Python, $SettingsPath, $CodexBinDir, $compose, $override, $nextCli,
    (Join-Path $frontend '.next/BUILD_ID'),
    (Join-Path $frontend '.next/server/preview-props.json')
)) {
    if (-not (Test-Path -LiteralPath $required)) { throw "Missing required local path: $required" }
}
if ($DatabasePort -ne 55433 -or $ApiPort -ne 8010 -or $FrontendPort -ne 3110) {
    throw 'OAuth Codex ports are fixed to DB 55433, API 8010, and frontend 3110.'
}

function Get-Listener([int]$Port) {
    Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue
}
function Wait-PortFree([int]$Port) {
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        if (-not (Get-Listener $Port)) { return }
        Start-Sleep -Milliseconds 500
    }
    throw "Port $Port is still occupied after stopping the Docker app service."
}
function Wait-Http([string]$Url) {
    for ($attempt = 0; $attempt -lt 60; $attempt++) {
        try {
            $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 2
            if ($response.StatusCode -eq 200) { return }
        } catch { }
        Start-Sleep -Seconds 1
    }
    throw "Not ready: $Url. Inspect logs in $logs."
}

New-Item -ItemType Directory -Force -Path $logs | Out-Null
$composeArgs = @(
    'compose', '--project-name', 'uhkegryo-oauth-local', '--env-file', $SettingsPath,
    '-f', $compose, '-f', $override
)

# Recreate only the existing DB container to add a loopback-only port. Its named volume is preserved.
& docker @composeArgs up -d --no-deps app-db
if ($LASTEXITCODE -ne 0) { throw 'Could not expose the existing app DB on loopback.' }

# The Linux API cannot execute the signed Windows Codex CLI. Keep DB/search/MCP untouched.
& docker @composeArgs stop api frontend
if ($LASTEXITCODE -ne 0) { throw 'Could not stop the Docker API/frontend services.' }
Wait-PortFree $ApiPort
Wait-PortFree $FrontendPort

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss-fff'
$savedCodexBinDir = $env:CODEX_BIN_DIR
try {
    $env:CODEX_BIN_DIR = $CodexBinDir
    $apiArguments = @(
        '-m', 'backend.local_codex', '--oauth-settings', ('"{0}"' -f $SettingsPath),
        '--database-port', $DatabasePort, '--port', $ApiPort,
        '--frontend-port', $FrontendPort, '--search-url', $SearchUrl
    )
    $api = Start-Process -FilePath $Python -ArgumentList $apiArguments `
        -WorkingDirectory $repository -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $logs "oauth-api-$stamp.out.log") `
        -RedirectStandardError (Join-Path $logs "oauth-api-$stamp.err.log")
} finally {
    $env:CODEX_BIN_DIR = $savedCodexBinDir
}
Write-Output "Host API launched: PID $($api.Id)"
Wait-Http "http://127.0.0.1:$ApiPort/health"

$nodeExe = (Get-Command node -ErrorAction Stop).Source
$savedOrigin = $env:AGENT_API_ORIGIN
$savedDemo = $env:NEXT_PUBLIC_UI_DEMO
try {
    $env:AGENT_API_ORIGIN = "http://127.0.0.1:$ApiPort"
    $env:NEXT_PUBLIC_UI_DEMO = '0'
    $ui = Start-Process -FilePath $nodeExe `
        -ArgumentList ('"{0}" start -p {1} -H 127.0.0.1' -f $nextCli, $FrontendPort) `
        -WorkingDirectory $frontend -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $logs "oauth-frontend-$stamp.out.log") `
        -RedirectStandardError (Join-Path $logs "oauth-frontend-$stamp.err.log")
} finally {
    $env:AGENT_API_ORIGIN = $savedOrigin
    $env:NEXT_PUBLIC_UI_DEMO = $savedDemo
}
Write-Output "Host frontend launched: PID $($ui.Id)"
Wait-Http "http://127.0.0.1:$FrontendPort/"
Wait-Http "http://127.0.0.1:$FrontendPort/service-health"
Write-Output "Ready: http://localhost:$FrontendPort. No model request was sent."
Write-Output "Logs: $logs"
