param(
    [string]$EnvFile = ".env.portfolio.local",
    [switch]$SkipVercelUpdate
)

$ErrorActionPreference = "Stop"
$repositoryRoot = Split-Path -Parent $PSScriptRoot
$frontendRoot = Join-Path $repositoryRoot "frontend"
$runDir = Join-Path $repositoryRoot ".local-run\portfolio-host"
$pidFile = Join-Path $runDir "pids.json"
$tunnelPidFile = Join-Path $runDir "tunnel-pid.json"
$originFile = Join-Path $runDir "tunnel-origin.txt"
$deployedOriginFile = Join-Path $runDir "deployed-origin.txt"
$startScript = Join-Path $PSScriptRoot "portfolio-host-start.ps1"
$stopScript = Join-Path $PSScriptRoot "portfolio-host-stop.ps1"
$tunnelScript = Join-Path $PSScriptRoot "portfolio-host-tunnel.ps1"
$envPath = if ([IO.Path]::IsPathRooted($EnvFile)) { $EnvFile } else { Join-Path $repositoryRoot $EnvFile }
$publicOrigin = "https://uhkegryo-xi.vercel.app"
$vercelVersion = "50.6.1"

function Import-PortfolioEnvironment {
    if (-not (Test-Path -LiteralPath $envPath -PathType Leaf)) {
        throw "Portfolio environment is missing. Do not create new secrets; restore the existing ignored environment file."
    }
    foreach ($line in [IO.File]::ReadAllLines($envPath)) {
        if (-not $line -or $line.StartsWith("#")) { continue }
        $parts = $line.Split("=", 2)
        if ($parts.Count -ne 2 -or $parts[0] -notmatch '^[A-Z0-9_]+$') {
            throw "Invalid portfolio environment entry."
        }
        [Environment]::SetEnvironmentVariable($parts[0], $parts[1], "Process")
    }
}

function Test-TrackedProcess($record) {
    if (-not $record -or -not $record.id -or -not $record.started_ticks) { return $false }
    $process = Get-Process -Id ([int]$record.id) -ErrorAction SilentlyContinue
    return $process -and $process.StartTime.ToUniversalTime().Ticks -eq [long]$record.started_ticks
}

function Test-HostReady {
    if (-not (Test-Path -LiteralPath $pidFile -PathType Leaf)) { return $false }
    try {
        $parsedRecords = Get-Content -Raw -LiteralPath $pidFile | ConvertFrom-Json
        $records = @($parsedRecords | ForEach-Object { $_ })
        if ($records.Count -ne 2) { return $false }
        foreach ($record in $records) {
            if (-not (Test-TrackedProcess $record)) { return $false }
        }
        $response = Invoke-WebRequest -UseBasicParsing -TimeoutSec 5 `
            -Headers @{ "x-portfolio-gateway-secret" = $env:PORTFOLIO_GATEWAY_SECRET } `
            -Uri "http://127.0.0.1:$($env:PORTFOLIO_FRONTEND_PORT)/service-health"
        return $response.StatusCode -eq 200
    } catch {
        return $false
    }
}

function Remove-StaleTunnelRecord {
    if (-not (Test-Path -LiteralPath $tunnelPidFile -PathType Leaf)) { return }
    $record = Get-Content -Raw -LiteralPath $tunnelPidFile | ConvertFrom-Json
    if (Test-TrackedProcess $record) { return }
    Remove-Item -LiteralPath $tunnelPidFile -Force
    Remove-Item -LiteralPath $originFile -Force -ErrorAction SilentlyContinue
}

function Test-TunnelReady {
    if (-not (Test-Path -LiteralPath $tunnelPidFile -PathType Leaf)) { return $false }
    if (-not (Test-Path -LiteralPath $originFile -PathType Leaf)) { return $false }
    $record = Get-Content -Raw -LiteralPath $tunnelPidFile | ConvertFrom-Json
    if (-not (Test-TrackedProcess $record)) { return $false }
    $origin = [IO.File]::ReadAllText($originFile).Trim()
    return $origin -match '^https://[a-z0-9-]+\.trycloudflare\.com$'
}

function Wait-PublicHealth {
    for ($attempt = 0; $attempt -lt 60; $attempt++) {
        try {
            $response = Invoke-WebRequest -UseBasicParsing -TimeoutSec 10 -Uri "$publicOrigin/service-health"
            if ($response.StatusCode -eq 200) { return }
        } catch {}
        Start-Sleep -Seconds 2
    }
    throw "Public service health did not become ready after the Vercel redeploy."
}

Import-PortfolioEnvironment
New-Item -ItemType Directory -Path $runDir -Force | Out-Null

if (Test-HostReady) {
    Write-Host "[1/4] Local database, search, API, and gateway are already ready."
} else {
    Write-Host "[1/4] Cleaning only stale tracked runtime records."
    & $stopScript -EnvFile $envPath
    Write-Host "[2/4] Starting the isolated local runtime."
    & $startScript -EnvFile $envPath
}

Remove-StaleTunnelRecord
if (Test-TunnelReady) {
    Write-Host "[3/4] Cloudflare Quick Tunnel is already ready."
} else {
    Write-Host "[3/4] Starting a new Cloudflare Quick Tunnel."
    & $tunnelScript
}

$origin = [IO.File]::ReadAllText($originFile).Trim()
if ($origin -notmatch '^https://[a-z0-9-]+\.trycloudflare\.com$') {
    throw "The tunnel did not publish a valid HTTPS origin."
}

if ($SkipVercelUpdate) {
    Write-Host "CHECK COMPLETE: local runtime and Quick Tunnel are ready."
    Write-Host "Vercel update was intentionally skipped; this mode is only for local validation."
    return
}

$deployedOrigin = ""
if (Test-Path -LiteralPath $deployedOriginFile -PathType Leaf) {
    $deployedOrigin = [IO.File]::ReadAllText($deployedOriginFile).Trim()
}
if ($deployedOrigin -ne $origin) {
    Write-Host "[4/4] Updating the Vercel server origin and redeploying production."
    Push-Location $frontendRoot
    try {
        & npx.cmd --yes "vercel@$vercelVersion" whoami | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "The existing Vercel login is unavailable. Run 'npx vercel login' yourself, then retry."
        }
        $originInputFile = Join-Path $runDir "vercel-origin-input.tmp"
        [IO.File]::WriteAllText($originInputFile, $origin, [Text.UTF8Encoding]::new($false))
        try {
            $envUpdate = Start-Process -FilePath "npx.cmd" -ArgumentList @(
                "--yes", "vercel@$vercelVersion", "env", "add",
                "PORTFOLIO_GATEWAY_ORIGIN", "production", "--force", "--yes", "--sensitive"
            ) -WorkingDirectory $frontendRoot -NoNewWindow -Wait -PassThru `
                -RedirectStandardInput $originInputFile
            if ($envUpdate.ExitCode -ne 0) { throw "Vercel origin update failed." }
        } finally {
            Remove-Item -LiteralPath $originInputFile -Force -ErrorAction SilentlyContinue
        }
        & npx.cmd --yes "vercel@$vercelVersion" redeploy $publicOrigin --target production
        if ($LASTEXITCODE -ne 0) { throw "Vercel production redeploy failed." }
    } finally {
        Pop-Location
    }
    Wait-PublicHealth
    [IO.File]::WriteAllText($deployedOriginFile, $origin, [Text.UTF8Encoding]::new($false))
} else {
    Write-Host "[4/4] Vercel already points to this tunnel."
    Wait-PublicHealth
}

Write-Host "READY: $publicOrigin"
Write-Host "Keep this notebook awake and connected while other people use the AI."

