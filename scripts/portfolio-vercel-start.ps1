param(
    [string]$EnvFile = ".env.portfolio"
)

$ErrorActionPreference = "Stop"
$repositoryRoot = Split-Path -Parent $PSScriptRoot
$baseCompose = Join-Path $repositoryRoot "compose.portfolio.yml"
$hybridCompose = Join-Path $repositoryRoot "compose.portfolio-vercel.yml"
$envPath = if ([System.IO.Path]::IsPathRooted($EnvFile)) {
    $EnvFile
} else {
    Join-Path $repositoryRoot $EnvFile
}

if (-not (Test-Path -LiteralPath $envPath -PathType Leaf)) {
    throw "Portfolio environment file is missing. Copy .env.portfolio.example and fill only approved values."
}

docker compose --env-file $envPath -f $baseCompose -f $hybridCompose config --quiet
if ($LASTEXITCODE -ne 0) { throw "Vercel hybrid portfolio configuration validation failed." }

# Foreground execution is deliberate. This starts no tunnel and publishes no API/database/search port.
docker compose --env-file $envPath -f $baseCompose -f $hybridCompose up --build
if ($LASTEXITCODE -ne 0) { throw "Vercel hybrid portfolio services stopped with an error." }
