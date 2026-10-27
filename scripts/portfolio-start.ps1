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
    throw "Portfolio environment file is missing. Copy .env.portfolio.example and fill only approved values."
}

docker compose --env-file $envPath -f $composeFile config --quiet
if ($LASTEXITCODE -ne 0) { throw "Portfolio configuration validation failed." }

# Foreground execution is deliberate: nothing is published automatically after restart.
docker compose --env-file $envPath -f $composeFile up --build
if ($LASTEXITCODE -ne 0) { throw "Portfolio services stopped with an error." }
