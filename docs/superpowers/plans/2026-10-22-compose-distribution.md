# Docker Compose Distribution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let an authorized recipient of the private repository start the complete local application with Docker Compose after supplying only their own OpenRouter key.

**Architecture:** The default Compose project contains a local application PostgreSQL database, one-shot migration service, API/worker, MCP, SearXNG, and the Next.js frontend. Langfuse and its storage dependencies move behind an `observability` profile so the default stack has no observability-secret requirement. An explicitly supplied `DATABASE_URL` continues to override the local database connection.

**Tech Stack:** Docker Compose v2, PostgreSQL 17, Python 3.12/FastAPI, Next.js 16/Node.js 22, SearXNG.

## Global Constraints

- Keep the repository private; do not change repository access or choose a license.
- Do not read or copy real API keys, databases, volumes, or logs.
- Do not stop or alter the existing 3100/8000/8080 runtime.
- Validate with a separate Compose project name and ports; never run `docker compose down -v`.
- Do not issue a paid LLM request.
- Keep UI, graph, logo, and application behavior unchanged.

---

### Task 1: Define the distribution contract

**Files:**
- Create: `backend/tests/test_compose_distribution.py`

- [ ] Add failing assertions for the default core services, migration dependency, frontend proxy, local database, external `DATABASE_URL` override, and optional observability profile.
- [ ] Run the focused test and confirm it fails because the services do not exist yet.

### Task 2: Package the backend, database, and frontend

**Files:**
- Modify: `docker-compose.yml`
- Create: `backend/db/run_migrations.py`
- Create: `frontend/Dockerfile`
- Create: `frontend/.dockerignore`
- Create: `.dockerignore`
- Modify: `.env.example`

- [ ] Add the app database and one-shot migration service.
- [ ] Add the frontend image and internal `http://api:8000` proxy configuration.
- [ ] Remove Langfuse from the default dependency chain and put every observability service behind the `observability` profile.
- [ ] Preserve an external database override and localhost-only host bindings.
- [ ] Run the focused contract test until green.

### Task 3: Document recipient operation

**Files:**
- Modify: `README.md`

- [ ] Document private-repository access, `.env` creation, required OpenRouter key, start/stop/restart/update commands, URLs, volume persistence, external database override, observability profile, and troubleshooting.
- [ ] State the localhost/development security boundary and that no license or repository visibility was changed.

### Task 4: Verify in isolation and publish

- [ ] Run Compose interpolation and focused tests.
- [ ] Start an isolated stack with a unique project name and non-conflicting ports.
- [ ] Verify DB migration, API health, frontend-to-API health, catalog/search dependency connectivity, and volume persistence without an LLM request.
- [ ] Stop only the isolated containers without deleting volumes.
- [ ] Run the relevant backend tests and frontend production build.
- [ ] Commit without signing, push `main`, and report remote/CI status separately from local verification.
