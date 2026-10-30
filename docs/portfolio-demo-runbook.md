# Anonymous portfolio demo runbook

This runtime is separate from the private Google/Codex runtime. It has its own
Compose project, PostgreSQL volume, network, search service, API, and frontend.
It never mounts or reads the private environment file.

## Before a local start

1. Copy `.env.portfolio.example` to the ignored `.env.portfolio` file.
2. Fill only separately approved values. The model and every allowlist entry
   must use an explicit `:free` ID. The public origin must be the exact temporary
   HTTPS origin, and the evaluation end must include a timezone.
3. After API/network use is approved, obtain the current authenticated
   OpenRouter `/models` response and set `PORTFOLIO_MODEL_CATALOG_FILE` to that
   file. The API container mounts it read-only. Startup fails unless the selected
   allowlisted model is present and `prompt`, `completion`, `request`, and every
   other published pricing field are numeric zero. The file must also be newer
   than `PORTFOLIO_MODEL_CATALOG_MAX_AGE_SECONDS` (one hour by default). The
   application never substitutes a mock or stale catalog.

Start in the foreground:

```powershell
.\scripts\portfolio-start.ps1
```

Stop explicitly:

```powershell
.\scripts\portfolio-stop.ps1
```

The stop command preserves the dedicated database volume. There is no automatic
data deletion policy. All services use `restart: "no"`, so a PC or Docker restart
does not publish the demo again.

## Future temporary HTTPS tunnel

Only the loopback frontend target `http://127.0.0.1:3120` may be used. The API,
PostgreSQL, and SearXNG have no host ports in this Compose file and must never be
tunnel targets. Tunnel software installation, account setup, link creation, and
external exposure require separate approval. Set the resulting exact HTTPS
origin before starting so secure cookies, CORS, and mutation-origin checks agree.

## Vercel Hobby frontend + PC backend

This mode keeps the public page at one Vercel production origin while the
isolated portfolio backend runs only during an evaluation window.

### Windows Ollama host: manual lifetime

The host environment must set `PORTFOLIO_EVALUATION_ENDS_AT=disabled` to opt
into manual lifetime management. A missing, blank, misspelled, or otherwise
invalid value fails closed; an ISO-8601 timestamp still enables the older
automatic-close behavior. `disabled` removes only the date cutoff. The UTC-day
40-call budget, one worker, gateway secret, exact-origin checks, route allowlist,
and owner-scoped cookies remain enforced.

Run the host stack explicitly:

```powershell
.\scripts\portfolio-host-stop.ps1
.\scripts\portfolio-host-start.ps1
```

Running stop first is safe after a reboot: PID records include both the process
ID and start time, so a reused PID is not terminated, and stale records are
removed. Compose `down` does not remove volumes, so isolated conversations,
personal terms, and the daily usage counter survive a stop or reboot. Start
refuses an existing PID record or occupied loopback port instead of killing an
unrelated process. The ignored environment file is reused; do not run
`portfolio-host-new-env.ps1` on every start because it intentionally creates
new secrets.

The start command launches only the loopback database/search/API/frontend. It
does not start Cloudflare or update Vercel. After every reboot, start the Quick
Tunnel separately:

```powershell
.\scripts\portfolio-host-tunnel.ps1
```

The tunnel helper resolves `cloudflared.exe` from `PATH` and then the official
Winget install location used on this PC. It fails closed if neither exists.

Read the newly written `.local-run/portfolio-host/tunnel-origin.txt`, replace
only Vercel's server-side `PORTFOLIO_GATEWAY_ORIGIN`, and redeploy production.
Quick Tunnel hostnames change after restart; the gateway secret must be reused,
not regenerated. No Windows login task, service, firewall rule, or router port
forward is installed by these scripts.

### Public and private paths

- Vercel serves `/` and its static assets. Its Node Route Handlers own
  `/api/*` and `/service-health` and forward only to the configured
  `PORTFOLIO_GATEWAY_ORIGIN`.
- The Quick Tunnel target remains the loopback portfolio frontend at
  `http://127.0.0.1:3120`. PostgreSQL, FastAPI, and SearXNG retain no host
  ports and are never tunnel targets.
- The local frontend accepts API and health traffic only when the server-only
  `PORTFOLIO_GATEWAY_SECRET` injected by the Vercel proxy matches. A request
  cannot supply or select an alternate upstream URL.
- The private Google/Codex frontend and API, admin/auth routes, ports
  3110/8010/55433, and private environment file are not part of this project.

### Vercel project settings to enter after approval

Use `frontend` as the project root and the existing Next.js build settings.
Copy the variable names from `frontend/vercel.env.example`; do not upload that
example as an environment file. Mark `PORTFOLIO_GATEWAY_SECRET` as a Secret.
Do not add an OpenRouter key, database URL, Google OAuth value, Codex setting,
or the private local environment to Vercel.

Use exactly one stable production origin for `PORTFOLIO_PUBLIC_ORIGIN` and
`ALLOWED_ORIGINS` in the local `.env.portfolio`. Preview domains intentionally
fail the backend origin check rather than broadening CORS or CSRF rules.

### Evaluation start

1. After credential creation is separately approved, place the same random
   gateway secret in the local ignored `.env.portfolio` and in the Vercel
   server-only Secret.
2. Start the isolated stack in the foreground with
   `./scripts/portfolio-vercel-start.ps1`. This does not install or start a
   tunnel.
3. After tunnel execution is separately approved, start a Quick Tunnel whose
   only target is `http://127.0.0.1:3120`.
4. Set `PORTFOLIO_GATEWAY_ORIGIN` to that exact HTTPS origin and create a new
   Vercel production deployment. Environment changes do not alter an existing
   deployment.
5. Verify `/service-health`, anonymous session cookie continuity, CSRF rejection
   for a different Origin, image search, and one approved model call before
   sharing the stable Vercel production URL.

Quick Tunnel hostnames change on every new tunnel. Each change therefore needs
an updated `PORTFOLIO_GATEWAY_ORIGIN` and a new Vercel deployment. The gateway
secret should not change merely because the temporary hostname changed.

### Evaluation stop and offline behavior

Stop the Quick Tunnel first, then run `./scripts/portfolio-vercel-stop.ps1`.
The Vercel page remains available, but health and API requests return a
non-cacheable 503 and the UI says that the demo is not currently operating.
There is no fallback to the private Codex runtime or a paid model. All Compose
services still use `restart: "no"`, so restarting the PC does not publish the
demo automatically. The stop helper preserves the isolated database volume.

## Boundaries

- The evaluator is anonymous and each browser receives a random owner cookie;
  repository queries remain owner-scoped.
- Admin, invite, transfer, auth, API documentation, and local Codex profile
  routes are unavailable in portfolio mode.
- Every actual completion request reserves one UTC-day database counter before
  provider I/O. The maximum is 40, including retries and personal-term calls.
- One worker processes AI jobs. A full daily budget or provider 402/429 stops
  without retrying or switching to another provider/model.
- Langfuse and MCP are disabled, Uvicorn access logging is disabled, and secrets
  are server-only. Questions and generated content still persist in the isolated
  portfolio database because automatic deletion was not approved.
- Search continues through the existing local SearXNG/Pinterest path. Search
  terms and outbound search requests go to the configured search providers;
  prompts and conversation context go to the approved OpenRouter model only.
