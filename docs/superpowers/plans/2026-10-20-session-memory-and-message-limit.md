# Session Memory and Message Limit Implementation Plan

> **For agentic workers:** Use the installed implementation and independent review skills. Preserve the approved personal-main workflow.

**Goal:** Carry grounded character-reference conditions across a conversation and admit at most 20 unique user messages per session.

**Architecture:** Keep source-backed topic, confirmed conditions, exclusions and recommendation scope in the existing session JSON. Count actual admitted jobs under the existing PostgreSQL session admission lock; do not maintain a second resettable counter. The frontend displays server usage and preserves ambiguous submission identity.

**Tech Stack:** Existing FastAPI/asyncpg/PostgreSQL, Next.js/React, Node tests, pytest and Playwright.

## Global Constraints

- Base: `f3a5c854b8af55dec9fb5c9fee3aca0c1e4a2813`; personal repository `sechang405-maker/uhkegryo` only.
- Twenty accepted messages are allowed; the twenty-first new message receives HTTP 429 `SESSION_MESSAGE_LIMIT_REACHED`, retryable false.
- Accepted messages count once even when processing fails or retries; rejected submissions count zero. Session-lifetime idempotency lookup precedes admission limits.
- Resetting conversation context never resets admission counts. Actual new sessions start with empty memory and zero messages.
- Old sessions and results remain readable, including sessions already above twenty messages. No destructive migration or production-database test initialization.
- Keep character-only policy, original evidence and source/session checks, existing recommendation adoption and composer/paragraph behavior. No catalog expansion, deployment, authentication/global configuration or unrelated service changes.
- Real model verification uses a small non-sensitive synthetic flow only. Tests use a new explicitly marked isolated local PostgreSQL database.

## Task 1: Isolated verification environment

- [ ] Create a uniquely named `uhkegryo_session_memory_test_*` database on the existing personal loopback PostgreSQL instance. Verify database identity and an ownership marker before migrations or tests.
- [ ] Keep its DSN outside Git. Set `TEST_DATABASE_URL`, `MEMORY_TEST_DATABASE_URL` and `SESSION_LIMIT_TEST_DATABASE_URL` only in the guarded child test process. Block external test network access.

## Task 2: Grounded session memory

Files: `conversation_context.py`, `conversation_memory.py`, focused memory module, `reference_intent.py`, `recommendations.py`, worker integration and their tests. Extend the runtime drawing-dialogue supplement with the same distinctions.

- [ ] Write failing source-backed tests for explanation topic versus confirmed choice, then implement lazy compatible JSON state with a memory version, current topic, constraints, exclusions and recommendation scope.
- [ ] Reproduce `삼분할 구도가 뭐야?` -> `그리고 싶어`: select only `composition_rule_of_thirds`, preserving original source. No missing pose/category question.
- [ ] Recognize short contextual followups and specific-over-generic overlapping labels without inventing conditions from arbitrary assistant prose.
- [ ] Test `앉은 자세로` preserving thirds, `삼분할 빼줘` removing thirds, later explicit re-additions, and latest orientation replacement.
- [ ] Test explicit fresh topics, new characters and context reset clearing old constraints/recommendations/exclusions/board; unrelated/quoted/negative instructions remain guarded.
- [ ] Run a twenty-turn deterministic memory sequence, with original sources beyond the six recent rows and latest corrections/removals surviving reload.

## Task 3: Atomic server admission and compatible usage

Files: `job_repository.py`, `session_repository.py`, session usage helper, API schemas/routes and quota/repository/API tests.

- [ ] Write failing boundary and idempotency tests. Admit with permanent same-session idempotency lookup first, then actual-job count and insertion under one existing transaction lock.
- [ ] Session/list and submission payloads expose root `message_count`, `message_limit`, `remaining_messages`, `can_submit`. Preserve the existing job submission tuple/interface and cookie ownership.
- [ ] Verify the twentieth result is processed, twenty-first new key rejected, retry of an existing key at the limit returned, different-text key reuse rejected, failed accepted job still counted, insert rollback not counted.
- [ ] Run real isolated PostgreSQL races: distinct keys competing at nineteen; identical concurrent key; separate sessions; legacy over-limit rows; reads and new-session behavior.

## Task 4: Session UI and retry identity

Files: frontend page, submission/server-conversation helpers, focused usage helper/styles and tests.

- [ ] Show small remaining usage and limit notice; keep history/results accessible and new conversation action in the session UI, without answer buttons.
- [ ] Preserve accepted request identity for uncertain network retries across reload; synchronize server usage on restore/history and cross-tab focus. Do not create new model jobs for an existing failed-message retry.
- [ ] Verify restored twentieth results, stale tabs receiving server 429, new session zero count and existing over-limit sessions read-only. Keep demo independent.

## Task 5: Integration, independent review and publication

- [ ] Run complete backend tests against guarded isolated PostgreSQL, frontend tests and production build. Review memory and quota/UI separately, then their integration.
- [ ] Verify browser reload/history/new-session/limit flow using deterministic local mock data; verify actual repository/DB boundary and one bounded synthetic model/search flow.
- [ ] Snapshot existing runtime files before synchronization, copy only task-owned final files, and verify equality. Restart only the exact personal verification processes when required.
- [ ] Publish tested work directly to personal main with an expected-head lease. Verify remote file contents, local clean checkout, runtime equality and CI. Report passes/failures/skips separately.

## Queued followup (only after Tasks 1-5 are complete and verified)

- [ ] Place the left history popup Home and New Session buttons side by side. Change only their borders to the actual existing logo color token; preserve background/text colors, mobile fit, touch size and keyboard focus. Verify and publish this as a separate followup with separate evidence.
