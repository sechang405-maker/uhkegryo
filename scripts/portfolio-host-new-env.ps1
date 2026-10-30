param(
    [string]$EnvFile = ".env.portfolio.local",
    [string]$PublicOrigin = "https://uhkegryo-xi.vercel.app"
)

$ErrorActionPreference = "Stop"
$repositoryRoot = Split-Path -Parent $PSScriptRoot
$envPath = if ([IO.Path]::IsPathRooted($EnvFile)) { $EnvFile } else { Join-Path $repositoryRoot $EnvFile }
if (Test-Path -LiteralPath $envPath) {
    throw "Portfolio environment already exists; refusing to overwrite its database and gateway secrets."
}

function New-HexSecret([int]$bytes) {
    $buffer = [byte[]]::new($bytes)
    [Security.Cryptography.RandomNumberGenerator]::Fill($buffer)
    return [Convert]::ToHexString($buffer).ToLowerInvariant()
}

$startedAt = [DateTimeOffset]::UtcNow
$endsAt = $startedAt.AddDays(7)
$lines = @(
    "PORTFOLIO_POSTGRES_PASSWORD=$(New-HexSecret 32)",
    "PORTFOLIO_SEARXNG_SECRET=$(New-HexSecret 32)",
    "PORTFOLIO_GATEWAY_SECRET=$(New-HexSecret 48)",
    "PORTFOLIO_EVALUATION_STARTED_AT=$($startedAt.ToString('o'))",
    "PORTFOLIO_EVALUATION_ENDS_AT=$($endsAt.ToString('o'))",
    "PORTFOLIO_PUBLIC_ORIGIN=$($PublicOrigin.TrimEnd('/'))",
    "PORTFOLIO_DB_PORT=55434",
    "PORTFOLIO_SEARXNG_PORT=8081",
    "PORTFOLIO_API_PORT=8000",
    "PORTFOLIO_FRONTEND_PORT=3120",
    "LLM_BACKEND=ollama",
    "OLLAMA_BASE_URL=http://127.0.0.1:11434/v1",
    "OLLAMA_MODEL=qwen3.5:4b-q4_K_M",
    "OPENROUTER_API_KEY="
)
[IO.File]::WriteAllLines($envPath, $lines, [Text.UTF8Encoding]::new($false))
try {
    $acl = Get-Acl -LiteralPath $envPath
    $acl.SetAccessRuleProtection($true, $false)
    $rule = [Security.AccessControl.FileSystemAccessRule]::new(
        [Security.Principal.WindowsIdentity]::GetCurrent().Name,
        [Security.AccessControl.FileSystemRights]::FullControl,
        [Security.AccessControl.AccessControlType]::Allow
    )
    $acl.SetAccessRule($rule)
    Set-Acl -LiteralPath $envPath -AclObject $acl
} catch {
    Remove-Item -LiteralPath $envPath -Force -ErrorAction SilentlyContinue
    throw "Could not restrict the portfolio secret file to the current Windows account."
}
