param([string]$EnvFile = ".env.portfolio.local")

$ErrorActionPreference = "Stop"
$repositoryRoot = Split-Path -Parent $PSScriptRoot
$composeFile = Join-Path $repositoryRoot "compose.portfolio-ollama-host.yml"
$envPath = if ([IO.Path]::IsPathRooted($EnvFile)) { $EnvFile } else { Join-Path $repositoryRoot $EnvFile }
$pidFile = Join-Path $repositoryRoot ".local-run\portfolio-host\pids.json"
$tunnelPidFile = Join-Path $repositoryRoot ".local-run\portfolio-host\tunnel-pid.json"
$adminDatabaseScript = Join-Path $PSScriptRoot "portfolio-admin-db.ps1"

if (Test-Path -LiteralPath $tunnelPidFile) {
    $record = Get-Content -Raw -LiteralPath $tunnelPidFile | ConvertFrom-Json
    $process = Get-Process -Id $record.id -ErrorAction SilentlyContinue
    if ($process -and $process.StartTime.ToUniversalTime().Ticks -eq [long]$record.started_ticks) {
        Stop-Process -Id $record.id
        $process.WaitForExit(10000) | Out-Null
    }
    Remove-Item -LiteralPath $tunnelPidFile -Force
}

if (Test-Path -LiteralPath $pidFile) {
    foreach ($record in (Get-Content -Raw -LiteralPath $pidFile | ConvertFrom-Json)) {
        $process = Get-Process -Id $record.id -ErrorAction SilentlyContinue
        if ($process -and $process.StartTime.ToUniversalTime().Ticks -eq [long]$record.started_ticks) {
            Stop-Process -Id $record.id
            $process.WaitForExit(10000) | Out-Null
        }
    }
    Remove-Item -LiteralPath $pidFile -Force
}
if (Test-Path -LiteralPath $envPath) {
    docker compose --env-file $envPath -f $composeFile down --remove-orphans
    if ($LASTEXITCODE -ne 0) { throw "Isolated database/search services did not stop cleanly." }
}
& $adminDatabaseScript -Action Stop
