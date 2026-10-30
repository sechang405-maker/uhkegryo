param([string]$Cloudflared = "cloudflared.exe")

$ErrorActionPreference = "Stop"
$repositoryRoot = Split-Path -Parent $PSScriptRoot
$runDir = Join-Path $repositoryRoot ".local-run\portfolio-host"
$pidFile = Join-Path $runDir "tunnel-pid.json"
$originFile = Join-Path $runDir "tunnel-origin.txt"
$logFile = Join-Path $runDir "tunnel.log"
if (Test-Path -LiteralPath $pidFile) { throw "Tunnel PID record already exists." }
New-Item -ItemType Directory -Path $runDir -Force | Out-Null
$tunnel = Start-Process -FilePath $Cloudflared -ArgumentList @("tunnel", "--no-autoupdate", "--url", "http://127.0.0.1:3120", "--logfile", $logFile, "--loglevel", "info") -WorkingDirectory $repositoryRoot -WindowStyle Hidden -PassThru
[IO.File]::WriteAllText($pidFile, (@{ id = $tunnel.Id; started_ticks = $tunnel.StartTime.ToUniversalTime().Ticks } | ConvertTo-Json), [Text.UTF8Encoding]::new($false))
for ($attempt = 0; $attempt -lt 60; $attempt++) {
    Start-Sleep -Seconds 1
    if (Test-Path -LiteralPath $logFile) {
        $match = [regex]::Match((Get-Content -Raw -LiteralPath $logFile), 'https://[a-z0-9-]+\.trycloudflare\.com')
        if ($match.Success) {
            [IO.File]::WriteAllText($originFile, $match.Value, [Text.UTF8Encoding]::new($false))
            return
        }
    }
    if ($tunnel.HasExited) { throw "Cloudflare Quick Tunnel exited before publishing an origin." }
}
Stop-Process -Id $tunnel.Id -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
throw "Cloudflare Quick Tunnel origin was not published within 60 seconds."
