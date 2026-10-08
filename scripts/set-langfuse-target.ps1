param([Parameter(Mandatory)][ValidateSet('local','shared')][string]$Target)
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
$path = Join-Path $PWD '.env'
$content = [IO.File]::ReadAllText($path)
function ReadValues($file) {
    $values = @{}
    foreach ($line in [IO.File]::ReadAllLines((Join-Path $PWD $file))) {
        if ($line -match '^(LANGFUSE_[A-Z_]+)=(.*)$') { $values[$Matches[1]] = $Matches[2] }
    }
    return $values
}
if ($Target -eq 'shared') {
    $values = ReadValues '.env.langfuse-gcp'
    foreach ($name in @('LANGFUSE_APP_URL','LANGFUSE_PUBLIC_KEY','LANGFUSE_SECRET_KEY')) {
        if (-not $values[$name]) { throw "Missing $name in .env.langfuse-gcp" }
    }
    if (-not (Test-Path '.env.langfuse-local')) {
        $current = ReadValues '.env'
        if ($current['LANGFUSE_APP_URL']) { throw 'Local backup missing: restore local keys before the first shared switch.' }
        [IO.File]::WriteAllLines((Join-Path $PWD '.env.langfuse-local'), @(
            "LANGFUSE_PUBLIC_KEY=$($current['LANGFUSE_PUBLIC_KEY'])", "LANGFUSE_SECRET_KEY=$($current['LANGFUSE_SECRET_KEY'])"))
    }
    $values['LANGFUSE_HOST'] = $values['LANGFUSE_APP_URL']
    $values['LANGFUSE_BASE_URL'] = $values['LANGFUSE_APP_URL']
} else {
    $values = ReadValues '.env.langfuse-local'
    $values['LANGFUSE_APP_URL'] = ''
    $values['LANGFUSE_HOST'] = 'http://localhost:3000'
    $values['LANGFUSE_BASE_URL'] = 'http://localhost:3000'
}
foreach ($name in @('LANGFUSE_APP_URL','LANGFUSE_HOST','LANGFUSE_BASE_URL','LANGFUSE_PUBLIC_KEY','LANGFUSE_SECRET_KEY')) {
    $line = "$name=$($values[$name])"
    if ($content -match "(?m)^$name=.*$") {
        $content = [regex]::Replace($content, "(?m)^$name=[^\r\n]*", $line)
    } else { $content += "`r`n$line`r`n" }
}
[IO.File]::WriteAllText($path, $content, (New-Object Text.UTF8Encoding($false)))
Write-Host "Langfuse target: $Target. Restart the backend to apply; traces are not migrated."
