# Anonymous Portfolio Demo Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prepare a locally isolated, login-free portfolio runtime whose OpenRouter calls are free-model-only and atomically capped at 40 per UTC day.

**Architecture:** Add an explicit `anonymous_portfolio` runtime mode, a PostgreSQL-backed call budget at the outbound LLM boundary, and route gating that preserves anonymous owner isolation while removing private/admin surfaces. Run it from a standalone Compose project with only the frontend bound to loopback and no automatic restart.

**Tech Stack:** FastAPI, Pydantic settings, asyncpg/PostgreSQL, OpenAI-compatible OpenRouter client, Next.js, Docker Compose, pytest, Node test runner.

## Global Constraints

- Preserve the existing Google invite, owner-only Codex Luna, personal database, and stopped Langfuse practice environment.
- Do not create, discover, copy, register, or print API keys.
- Do not call a real model or expose any network service during this implementation.
- Portfolio AI worker concurrency is exactly 1 and every attempted outbound LLM call, including retries and personal-term generation, counts toward 40 per UTC day.
- Paid fallback and Codex fallback are forbidden; missing public origin, evaluation end time, key, or approved free model fails closed.
- Automatic permanent deletion of visitor data remains disabled until separately approved.

---

### Task 1: Portfolio settings and route boundary

**Files:**
- Modify: `backend/shared/config.py`
- Modify: `backend/main.py`
- Modify: `backend/routes/agent.py`
- Modify: `backend/routes/term_search.py`
- Modify: `frontend/lib/agent-submit.mjs`
- Modify: `frontend/lib/server-conversation.mjs`
- Modify: `frontend/lib/term-search.mjs`
- Test: `backend/tests/test_portfolio_runtime.py`
- Test: `frontend/tests/portfolio-runtime.test.mjs`

**Interfaces:**
- Produces `Settings.runtime_mode: Literal['standard', 'anonymous_portfolio']` and `Settings.is_portfolio`.
- Produces `require_portfolio_action(request, action)` for exact-origin mutation checks.

- [ ] Write tests that portfolio mode rejects Codex, non-official OpenRouter base URLs, non-free/unapproved models, missing key/origin/end time, concurrency other than 1, and enabled Langfuse.
- [ ] Run the focused tests and confirm they fail because portfolio settings and route gates do not exist.
- [ ] Implement the minimal settings validator, conditional router mounting/docs disabling, public-path allowlist, and action-header checks.
- [ ] Add matching frontend headers to agent submission, conversation creation, and term search.
- [ ] Run focused backend and frontend tests until green.

### Task 2: Atomic external LLM-call budget

**Files:**
- Create: `backend/db/migrations/014_portfolio_llm_daily_budget.sql`
- Create: `backend/services/portfolio_budget.py`
- Modify: `backend/services/llm.py`
- Modify: `backend/services/personal_term_generator.py`
- Test: `backend/tests/test_portfolio_budget.py`
- Test: `backend/tests/test_llm_adapter.py`
- Test: `backend/tests/test_personal_term_generator.py`

**Interfaces:**
- Produces `PortfolioBudget.reserve_llm_call(*, now=None) -> PortfolioBudgetUsage`.
- Raises `PortfolioDailyLimitReached` before any outbound transport call after 40 reservations for the UTC day.
- `LLMInterpretationAdapter` and `PersonalTermGenerator` consume one reservation immediately before each OpenRouter HTTP request.

- [ ] Write repository tests for first reservation, the fortieth success, the forty-first rejection, UTC-day separation, and concurrent reservations never exceeding 40.
- [ ] Run the tests and confirm failure because the migration/repository is absent.
- [ ] Implement the single-row-per-UTC-day counter using `INSERT ... ON CONFLICT ... DO UPDATE ... WHERE used < limit RETURNING`.
- [ ] Write adapter/generator tests proving rejected reservations prevent transport calls and retry calls reserve independently.
- [ ] Inject the budget at the shared outbound call boundary and run focused tests until green.

### Task 3: Portfolio worker and retry fail-closed behavior

**Files:**
- Modify: `backend/services/agent_worker.py`
- Modify: `backend/services/job_retry_recovery.py`
- Modify: `backend/services/failure_mapping.py`
- Test: `backend/tests/test_portfolio_worker.py`
- Test: `backend/tests/test_job_retry_recovery.py`

**Interfaces:**
- Portfolio workers use one slot and preserve the existing SearXNG/Pinterest search pipeline.
- `PortfolioDailyLimitReached`, 402, 403, 429, model/configuration errors are terminal and never trigger paid or Codex fallback.

- [ ] Write failing tests for worker concurrency enforcement, preserved search outcomes, and non-retryable portfolio budget/rate/auth failures.
- [ ] Implement only the portfolio-specific branch while leaving standard and Codex behavior unchanged.
- [ ] Run worker, retry, search, and local-Codex regression tests.

### Task 4: Standalone Compose and explicit lifecycle

**Files:**
- Create: `compose.portfolio.yml`
- Create: `.env.portfolio.example`
- Create: `scripts/start-portfolio-demo.ps1`
- Create: `scripts/stop-portfolio-demo.ps1`
- Modify: `.gitignore`
- Test: `backend/tests/test_portfolio_compose.py`

**Interfaces:**
- Compose project is fixed to `uhkegryo-portfolio` with a dedicated database volume.
- Only frontend is published to `127.0.0.1`; API, DB, and SearXNG have no host ports.
- Scripts never install or launch a tunnel and never print secret values.

- [ ] Write failing structural tests for project name, dedicated volume, `restart: 'no'`, one frontend loopback binding, no other ports, no observability services, and no Codex mounts/settings.
- [ ] Implement the standalone Compose file and secret-free environment template.
- [ ] Implement start preflight for key/model/origin/end-time inputs and stop scoped to the portfolio project without `-v`.
- [ ] Run structural tests and `docker compose config` only; do not start containers.

### Task 5: Regression verification and direct main commit

**Files:**
- Modify: `docs/superpowers/specs/2026-10-27-anonymous-portfolio-demo-design.md` only if verification exposes a contradiction.

- [ ] Run all focused portfolio tests, relevant auth/session/quota/search/LLM tests, complete backend pytest, complete frontend tests, and frontend production build.
- [ ] Inspect `git diff --check`, secret-like additions, exposed ports, runtime defaults, and confirm no existing secret file path/value entered the diff.
- [ ] Confirm no container/process/network/model call was started.
- [ ] Commit the verified approved changes directly to `main` with a scoped commit message and report commit state separately from test evidence.
