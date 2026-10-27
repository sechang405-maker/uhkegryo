param(
    [string]$EnvFile = ".env.portfolio"
)

$ErrorActionPreference = "Stop"
$repositoryRoot = Split-Path -Parent $PSScriptRoot
$composeFile = Join-Path $repositoryRoot "compose.portfolio.yml"
$envPath = if ([System.IO.Path]::IsPathRooted($EnvFile)) {
    $EnvFile
} else {
    Join-Path $repositoryRoot $EnvFile
}

if (-not (Test-Path -LiteralPath $envPath -PathType Leaf)) {
    throw "Portfolio environment file is required to identify the isolated project safely."
}

# Intentionally omit -v: stopping a demo never auto-deletes evaluator data.
docker compose --env-file $envPath -f $composeFile down --remove-orphans
if ($LASTEXITCODE -ne 0) { throw "Portfolio services did not stop cleanly." }
