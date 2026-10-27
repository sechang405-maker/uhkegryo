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
    throw "Portfolio environment file is required to identify the isolated project safely."
}

# Intentionally omit -v: stopping never auto-deletes evaluator data.
docker compose --env-file $envPath -f $baseCompose -f $hybridCompose down --remove-orphans
if ($LASTEXITCODE -ne 0) { throw "Vercel hybrid portfolio services did not stop cleanly." }
