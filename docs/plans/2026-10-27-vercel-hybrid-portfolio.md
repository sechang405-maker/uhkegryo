# Vercel Hobby + PC portfolio hybrid plan

## Boundary

- Vercel serves only the public portfolio frontend and a fixed server-side proxy.
- The proxy targets one operator-configured HTTPS gateway origin. No request value may choose the target.
- The PC Quick Tunnel targets only the isolated portfolio frontend on loopback port 3120. PostgreSQL, FastAPI, and SearXNG remain on the private Compose network.
- A server-only shared gateway secret authenticates Vercel-to-PC traffic. It is never prefixed with `NEXT_PUBLIC_` and is never returned to the browser.
- The private Google/Codex runtime, admin/auth routes, and ports 3110, 8010, and 55433 remain outside this deployment.

## Implementation

1. Add failing frontend tests for fixed-target proxying, secret replacement, fail-closed configuration, cookie forwarding, and the offline response.
2. Add failing gateway middleware tests for missing/wrong/correct secrets.
3. Implement a Node Route Handler proxy for `/api/*` and `/service-health` and a PC gateway check in `proxy.js`.
4. Add an exact Korean offline message while preserving the existing no-fallback behavior.
5. Add a Compose override and start/stop helpers for the hybrid gateway without publishing API, database, or search ports.
6. Add value-free Vercel environment examples and an operating runbook covering the required redeploy when a Quick Tunnel hostname changes.
7. Run focused tests, all frontend tests, a production build, Compose rendering, backend regression tests relevant to the portfolio boundary, and secret scanning before commit and push.

## Deferred external actions

Vercel project creation/linking, environment registration, deployment, Cloudflare installation or tunnel creation, credential creation, API key use, and real model calls require a separate approved step.
