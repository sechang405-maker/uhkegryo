param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("Start", "Stop")]
    [string]$Action
)

$ErrorActionPreference = "Stop"
$containerName = "uhkegryo-oauth-local-app-db-1"
$expectedProject = "uhkegryo-oauth-local"
$expectedService = "app-db"
$expectedHostPort = "55433"
$expectedDataDestination = "/var/lib/postgresql/data"

function Get-ValidatedAdminDatabase {
    $raw = & docker inspect $containerName 2>$null
    if ($LASTEXITCODE -ne 0 -or -not $raw) {
        throw "The existing administrator database container was not found. It will not be recreated automatically."
    }
    $parsedItems = ($raw -join [Environment]::NewLine) | ConvertFrom-Json
    $items = @($parsedItems | ForEach-Object { $_ })
    if ($items.Count -ne 1) { throw "Administrator database inspection was ambiguous." }
    $item = $items[0]
    $labels = $item.Config.Labels
    if ($labels.'com.docker.compose.project' -ne $expectedProject) {
        throw "Administrator database Compose project label does not match."
    }
    if ($labels.'com.docker.compose.service' -ne $expectedService) {
        throw "Administrator database Compose service label does not match."
    }
    $bindings = @($item.HostConfig.PortBindings.'5432/tcp')
    if (
        $bindings.Count -ne 1 -or
        $bindings[0].HostIp -ne "127.0.0.1" -or
        $bindings[0].HostPort -ne $expectedHostPort
    ) {
        throw "Administrator database loopback port binding does not match."
    }
    $dataMounts = @($item.Mounts | Where-Object {
        $_.Type -eq "volume" -and $_.Destination -eq $expectedDataDestination
    })
    if ($dataMounts.Count -ne 1) {
        throw "Administrator database persistent volume does not match."
    }
    return $item
}

$database = Get-ValidatedAdminDatabase
if ($Action -eq "Start") {
    if (-not $database.State.Running) {
        & docker start $containerName | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "Existing administrator database did not start." }
    }
    for ($attempt = 0; $attempt -lt 60; $attempt++) {
        $database = Get-ValidatedAdminDatabase
        if ($database.State.Running -and $database.State.Health.Status -eq "healthy") {
            Write-Output "administrator-db-ready"
            return
        }
        Start-Sleep -Seconds 1
    }
    throw "Existing administrator database did not become healthy."
}

if ($database.State.Running) {
    & docker stop --time 20 $containerName | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Existing administrator database did not stop." }
}
$database = Get-ValidatedAdminDatabase
if ($database.State.Running) { throw "Existing administrator database is still running." }
Write-Output "administrator-db-stopped"

