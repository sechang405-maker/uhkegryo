param(
    [string]$Project = 'proj2-509406',
    [string]$Zone = 'us-central1-a',
    [string]$AdminEmail,
    [string]$Domain
)
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
function Invoke-Gcloud {
    & gcloud @args
    if ($LASTEXITCODE -ne 0) { throw 'gcloud command failed; inspect existing resources before retrying.' }
}
function SecretHex {
    $bytes = New-Object byte[] 32
    $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
    return ([BitConverter]::ToString($bytes)).Replace('-', '').ToLowerInvariant()
}
$instance = 'langfuse-shared'
$region = $Zone.Substring(0, $Zone.Length - 2)
if (-not $AdminEmail) { $AdminEmail = (Invoke-Gcloud auth list '--filter=status:ACTIVE' '--format=value(account)').Trim() }
$existing = Invoke-Gcloud compute instances list "--project=$Project" "--filter=name=$instance" '--format=value(name)'
if ($existing) { throw 'VM already exists. Use the start/stop instructions; this script creates a fresh deployment.' }
if (Test-Path '.env.langfuse-gcp') { throw 'Deployment credentials already exist. Preserve them and inspect resources before retrying.' }
Invoke-Gcloud compute addresses create langfuse-shared-ip "--project=$Project" "--region=$region"
$ip = (Invoke-Gcloud compute addresses describe langfuse-shared-ip "--project=$Project" "--region=$region" '--format=value(address)').Trim()
if (-not $Domain) { $Domain = "$ip.sslip.io" }
if ($Domain -notmatch '^[a-zA-Z0-9.-]+$') { throw 'Domain must be a hostname without protocol or path.' }
$envLines = @("LANGFUSE_DOMAIN=$Domain", "LANGFUSE_APP_URL=https://$Domain", "LANGFUSE_ADMIN_EMAIL=$AdminEmail")
foreach ($name in @('LANGFUSE_NEXTAUTH_SECRET','LANGFUSE_SALT','LANGFUSE_ENCRYPTION_KEY',
    'LANGFUSE_POSTGRES_PASSWORD','LANGFUSE_CLICKHOUSE_PASSWORD','LANGFUSE_REDIS_AUTH',
    'LANGFUSE_MINIO_ROOT_PASSWORD','LANGFUSE_ADMIN_PASSWORD')) {
    $envLines += "$name=$(SecretHex)"
}
$envLines += "LANGFUSE_PUBLIC_KEY=pk-lf-$(SecretHex)"
$envLines += "LANGFUSE_SECRET_KEY=sk-lf-$(SecretHex)"
[IO.File]::WriteAllLines((Join-Path $PWD '.env.langfuse-gcp'), $envLines)
# Resolve locally, then ship only Langfuse services; app credentials never leave this machine.
$config = & docker compose --env-file .env --env-file .env.langfuse-gcp -f docker-compose.yml -f docker-compose.langfuse-gcp.yml config --format json
if ($LASTEXITCODE -ne 0) { throw 'Compose validation failed.' }
$config = $config | ConvertFrom-Json
foreach ($name in @($config.services.PSObject.Properties.Name)) {
    if ($name -notin @('langfuse-web','langfuse-worker','postgres','clickhouse','redis','minio','proxy')) {
        $config.services.PSObject.Properties.Remove($name)
    }
}
$config.name = 'langfuse-shared'
$config.services.proxy.volumes[0].source = '/opt/langfuse/Caddyfile'
$utf8 = New-Object Text.UTF8Encoding($false)
[IO.File]::WriteAllText((Join-Path $PWD '.env.langfuse-compose.json'), ($config | ConvertTo-Json -Depth 40), $utf8)
$rules = Invoke-Gcloud compute firewall-rules list "--project=$Project" '--filter=name=langfuse-shared-web' '--format=value(name)'
if (-not $rules) {
    Invoke-Gcloud compute firewall-rules create langfuse-shared-web "--project=$Project" '--network=default' '--allow=tcp:80,tcp:443' '--target-tags=langfuse-shared' '--source-ranges=0.0.0.0/0'
}
Invoke-Gcloud compute instances create $instance "--project=$Project" "--zone=$Zone" '--machine-type=e2-standard-4' '--image-family=ubuntu-2404-lts-amd64' '--image-project=ubuntu-os-cloud' '--boot-disk-size=50GB' '--boot-disk-type=pd-balanced' "--address=$ip" '--tags=langfuse-shared' '--no-service-account' '--no-scopes' '--max-run-duration=4h' '--instance-termination-action=STOP' '--no-restart-on-failure'
Invoke-Gcloud compute ssh $instance "--project=$Project" "--zone=$Zone" '--quiet' '--command=sudo apt-get update && sudo apt-get install -y docker.io docker-compose-v2 && sudo install -d -m 700 /opt/langfuse'
Invoke-Gcloud compute scp '.env.langfuse-compose.json' "${instance}:compose.json" "--project=$Project" "--zone=$Zone" '--quiet'
Invoke-Gcloud compute scp 'deploy/langfuse/Caddyfile' "${instance}:Caddyfile" "--project=$Project" "--zone=$Zone" '--quiet'
Invoke-Gcloud compute ssh $instance "--project=$Project" "--zone=$Zone" '--quiet' '--command=sudo mv compose.json Caddyfile /opt/langfuse/ && sudo chmod 600 /opt/langfuse/compose.json && sudo docker compose -f /opt/langfuse/compose.json up -d'
Write-Host "Langfuse: https://$Domain (health and trace receipt still need verification)"
Write-Host 'Credentials: .env.langfuse-gcp. VM automatically stops 4 hours after each start.'
