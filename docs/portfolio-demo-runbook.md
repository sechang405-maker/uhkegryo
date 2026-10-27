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
