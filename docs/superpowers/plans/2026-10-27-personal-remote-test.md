# Personal Remote Test Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a fail-closed, owner-only personal remote test mode with a server-only gateway proxy and mock-only regression coverage.

**Architecture:** A dedicated backend policy validates configuration, gateway provenance, CSRF origin, and owner account state. A dedicated Next.js server proxy owns the gateway secret and validates public-origin requests and redirects. Existing local and anonymous portfolio modes remain separate.

**Tech Stack:** FastAPI/Pydantic, Next.js Node route handlers, pytest, Node test runner.

**Spec:** `docs/superpowers/specs/2026-10-27-personal-remote-test-design.md`

## Global Constraints

- No remote push, PR, deployment, tunnel, secret/OAuth changes, real service/model/API calls, or service restarts.
- Preserve localhost-only Codex behavior and forbid Codex from `anonymous_portfolio`.
- Missing exact origin/callback/secret/owner settings fail closed.
- Tests use only synthetic values and in-memory fakes.

## Review Focus

- Missing or spoofed gateway Host/secret must never reach a protected handler.
- Expired or wrong-account sessions must not expose invite/admin fallbacks.
- Cross-site mutations and forged Origin headers must fail.
- Proxy redirects/cookies must preserve safe auth behavior without leaking the secret.
- Standard localhost and anonymous portfolio settings must retain current behavior.

---

### Task 1: Backend configuration and access policy

**Files:**
- Modify: `backend/shared/config.py`
- Create: `backend/services/personal_remote_access.py`
- Test: `backend/tests/test_personal_remote_access.py`

**Interfaces:**
- Produces `Settings.is_personal_remote_test`.
- Produces `gateway_request_allowed(settings, request)`, `is_login_exception(path)`, and `owner_account_allowed(settings, account)`.

- [ ] Write tests for complete configuration, missing settings, portfolio rejection, Host/origin/secret forgery, owner/other admin/unregistered/expired cases.
- [ ] Run and observe expected failures.
- [ ] Implement the minimal policy and settings validation.
- [ ] Run focused tests to green.

### Task 2: Backend route enforcement

**Files:**
- Modify: `backend/main.py`
- Modify: `backend/routes/auth.py`
- Test: `backend/tests/test_personal_remote_access.py`

**Interfaces:**
- Gateway middleware protects every request; only auth start/callback bypass session lookup.
- Personal mode exposes only auth start/callback/me/logout and rejects unregistered/non-owner callbacks.

- [ ] Add failing ASGI/fake-service tests for session expiry, logout, CSRF, direct gateway request, and route exposure.
- [ ] Implement middleware and callback restrictions without relaxing the localhost guard.
- [ ] Run focused and local/portfolio regressions.

### Task 3: Server-only Vercel proxy

**Files:**
- Create: `frontend/lib/personal-remote-gateway-proxy.mjs`
- Modify: `frontend/app/api/[...path]/route.js`
- Modify: `frontend/app/service-health/route.js`
- Modify: `frontend/proxy.js`
- Modify: `frontend/next.config.mjs`
- Modify: `frontend/vercel.env.example`
- Test: `frontend/tests/personal-remote-gateway-proxy.test.mjs`

**Interfaces:**
- `createPersonalRemoteGatewayProxy({env, fetchImpl})` returns a route handler using server-only env.

- [ ] Write failing tests for missing config, public Origin/Host spoofing, direct secret injection, cookie preservation, redirect allowlist, and secret non-reflection.
- [ ] Implement minimal proxy and personal private-route gate.
- [ ] Run focused Node tests and build when dependencies are available.

### Task 4: Verification and documentation

**Files:**
- Modify: this plan only to mark completed steps if useful.

- [ ] Run focused backend/frontend tests, local/portfolio regressions, diff checks, and secret scans available offline.
- [ ] Confirm no network/service/model action and no remote Git write occurred.
- [ ] Self-review the whole diff because subagent delegation is not authorized for this task.
