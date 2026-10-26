# Invite Demo Auth and Quota Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 약 10명의 사용자가 Google 로그인 후 운영자가 개인별로 배부한 초대 코드를 등록하고 계정별 누적 AI 요청 한도 안에서 어케그려를 사용하도록 한다.

**Architecture:** FastAPI가 Google OIDC와 불투명 앱 세션을 소유하고, 새 Google 신원은 개인별 초대 코드를 원자적으로 등록한 뒤에만 PostgreSQL 계정과 기존 `owner_id`에 연결한다. 이메일은 인증 속성일 뿐 허용 목록 키가 아니다. AI 호출 직전 원자적으로 1회를 예약하고 성공 결과 저장 후 확정하며, 실패·중복·내부 재시도는 같은 원장을 재사용하거나 해제한다. 기존 대화별 20회 제한은 별도로 유지한다.

**Tech Stack:** FastAPI, PostgreSQL/asyncpg, Next.js 16, Google OIDC, 기존 OpenRouter·SearXNG

**Spec:** `docs/superpowers/specs/2026-10-26-invite-demo-auth-quota-design.md`

## Global Constraints

- Google 로그인은 유지하되 이메일 허용 목록은 사용하지 않는다.
- 새 Google 신원은 운영자가 개인별로 배부한 유효한 초대 코드를 등록해야 서비스를 사용할 수 있다.
- 유효한 미사용 코드의 최초 등록은 자동 처리하고, 이후 같은 Google 계정 로그인에는 코드 재입력이나 관리자 승인을 요구하지 않는다.
- 다른 Google 계정으로 이전할 때만 관리자 승인을 요구하며 기존 `account_id`, owner, 누적 사용량과 잔여 한도를 유지한다.
- 신규 계정의 `ai_request_limit`은 0이다. 실제 초대·지급 숫자는 코드에 넣지 않는다.
- 성공한 AI 대화와 개인 용어 초안만 1회 차감한다.
- 실패·중복 제출·내부 재시도·고정 안내·이미지 재검색은 추가 차감하지 않는다.
- 기존 대화별 20회 제한은 유지하며 계정 누적값은 새 대화에서도 이어진다.
- 기존 익명 데이터는 보존하고 로그인 계정에 자동 병합하지 않는다.
- 실제 OAuth 자격 증명과 운영 DB migration은 각 단계 승인 전 만들거나 적용하지 않는다.

## Review Focus

- 남은 1회에 동시 요청 두 건: 정확히 하나만 예약되고 다른 하나는 한도 초과여야 한다(Task 1).
- 동일 idempotency key의 같은 요청·다른 요청·다른 계정: 재사용·충돌·격리가 각각 결정적이어야 한다(Task 1).
- 예약 뒤 계정 차단 또는 한도 감소: 새 예약만 막고 기존 원장과 확정 결과를 훼손하지 않아야 한다(Task 1).
- OAuth 콜백 재전송·동일 코드 동시 등록·초대 폐기·Google 이메일 변경: 계정 중복, 코드 재사용 또는 권한 우회가 없어야 한다(Task 2).
- 계정 이전: 검증된 새 Google 신원과 관리자 승인 없이는 불가능하고, 승인 후 기존 세션 폐기와 누적 사용량 보존이 결정적이어야 한다(Task 4).
- 공급자 성공 뒤 프로세스 중단: authoritative job/proposal 상태로 한 번만 확정 또는 해제되어야 한다(Task 3).

---

### Task 1: 계정·초대·누적 쿼터 DB 기반

**Files:**
- Create: `backend/db/migrations/009_invite_accounts_and_quota.sql`
- Create: `backend/schemas/demo_accounts.py`
- Create: `backend/services/demo_account_repository.py`
- Create: `backend/services/quota_repository.py`
- Create: `backend/tests/test_demo_account_repository.py`
- Create: `backend/tests/test_quota_repository.py`
- Modify: `docs/superpowers/specs/2026-10-26-invite-demo-auth-quota-design.md`

**Interfaces:**
- Produces: `DemoAccountRepository.create_invite()`, `accept_invite()`, `set_account_status()`, `set_ai_request_limit()`, `get_account()`
- Produces: `QuotaRepository.reserve()`, `charge()`, `release()`, `usage()`, `list_recovery_candidates()`
- Produces: `QuotaOperation`, `AccountUsage`, account/invite records and typed domain errors

- [x] **Step 1: owner 보존·초대 격리·신규 한도 0·관리자 변경 감사 실패 테스트를 작성한다.**
- [x] **Step 2: 원자적 마지막 1회, 동일키 재사용/충돌/계정 격리, 중복 확정/해제, 차단·한도 감소, stale 예약 후보 테스트를 작성하고 RED를 확인한다.**
- [x] **Step 3: migration 009에 accounts, invites, owner 연결, quota operations, quota adjustments와 제약·인덱스를 추가한다.**
- [x] **Step 4: 계정·초대 repository와 쿼터 repository를 최소 구현한다.**
- [x] **Step 5: 격리 PostgreSQL에서 새 테스트가 skip 없이 통과하고 기존 DB 테스트가 회귀하지 않는지 확인한다.**
- [ ] **Step 6: 문서·스키마·테스트만 main에 반영하고 정확 SHA CI를 확인한다. 운영 DB에는 migration을 적용하지 않는다.**

### Task 2: Google 로그인과 초대 제한

**Files:**
- Create: `backend/services/google_oidc.py`
- Create: `backend/services/auth_session_repository.py`
- Create: `backend/services/invite_code_repository.py`
- Create: `backend/routes/auth.py`
- Create: `backend/db/migrations/010_auth_sessions_and_invite_codes.sql`
- Modify: `backend/main.py`, `backend/shared/config.py`, `frontend/app/page.jsx`
- Create: `frontend/app/invite/page.jsx`, `frontend/app/invite/invite.css`
- Test: `backend/tests/test_google_oidc.py`, `backend/tests/test_auth_sessions.py`, `backend/tests/test_invite_code_repository.py`, `backend/tests/test_auth_routes.py`, `frontend/tests/invite-access.test.mjs`

**Interfaces:**
- Replaces: 이메일 기반 `DemoAccountRepository.accept_invite()`를 코드 기반 `redeem_invite_code()` 계약으로 전환
- Consumes: Task 1 account → owner 및 누적 쿼터 연결
- Produces: `/api/auth/google/start`, callback, invite redemption, `/api/auth/me`, `/api/auth/logout`

- [ ] **Step 1: invite code·OIDC flow·registration/app session·identity transfer migration과 실제 PostgreSQL 실패 테스트를 작성해 RED를 확인한다.**
- [ ] **Step 2: `InviteCodeRepository.issue()`, `redeem()`, `revoke()`, `request_identity_transfer()`, `approve_identity_transfer()`를 구현한다. 코드는 HMAC-SHA256만 저장하고 동일 코드 동시 등록 하나만 성공시킨다.**
- [ ] **Step 3: `AuthSessionRepository`의 OIDC flow, 제한 등록 세션, 정식 앱 세션 생성·조회·폐기·만료를 구현한다. 원문 토큰은 저장하지 않는다.**
- [ ] **Step 4: `GoogleOIDCClient.authorization_url()`과 `verify_callback()`을 구현하고 모의 token/JWKS 응답으로 state·nonce·PKCE·issuer·audience·서명·만료 검증을 고정한다.**
- [ ] **Step 5: 인증 라우트와 fail-closed middleware를 구현한다. `AUTH_MODE=google_invite`에서는 등록 전 계정이 auth·초대 등록 외 `/api`를 사용할 수 없고, `local` 기본값은 기존 실행을 보존한다.**
- [ ] **Step 6: `/invite` 최소 화면에서 Google 로그인과 코드 등록·오류·로그아웃을 제공하고 외부 return URL을 받지 않는지 검증한다.**
- [ ] **Step 7: auth token이 기존 owner-scoped repository에서 account owner로 해석되고 익명 owner와 자동 병합되지 않는 회귀를 검증한다.**
- [ ] **Step 8: 문서·코드만 main에 반영하고 정확 SHA CI를 확인한다. 운영 DB migration, 실제 OAuth 설정·초대 발급·실행본 활성화는 하지 않는다.**

### Task 3: 실제 AI 호출 차감 연결

**Files:**
- Modify: `backend/services/agent_worker.py`, `backend/services/personal_term_generator.py`
- Modify: `backend/services/job_retry_recovery.py`
- Test: `backend/tests/test_agent_quota.py`, `backend/tests/test_personal_term_quota.py`

**Interfaces:**
- Consumes: Task 1 `QuotaRepository`
- Produces: 대화 job/proposal과 quota operation의 일대일 수명주기

- [ ] **Step 1: 성공1·실패0·재시도0·고정안내0·재검색0과 장애 복구 테스트를 작성한다.**
- [ ] **Step 2: 실제 provider 호출 직전 reserve, 유효 결과 영속화 뒤 charge, 최종 실패 뒤 release를 연결한다.**
- [ ] **Step 3: 기존 idempotency와 재시도에서 operation이 하나뿐인지 격리 DB로 검증한다.**
- [ ] **Step 4: 대화 20회 제한과 계정 누적 제한이 독립적으로 동작하는지 검증한다.**
- [ ] **Step 5: 사용자 검수 후 main 반영·실행본·CI를 확인한다.**

### Task 4: 잔여량과 관리자 기능

**Files:**
- Create: `backend/routes/admin_demo.py`
- Modify: `backend/routes/agent.py`, `backend/routes/personal_terms.py`
- Modify: `frontend/app/page.jsx`, `frontend/app/globals.css`
- Test: `backend/tests/test_admin_demo.py`, `frontend/tests/account-quota.test.mjs`

**Interfaces:**
- Consumes: account role/status와 `AccountUsage`
- Produces: 사용자 잔여 AI 횟수, 관리자 초대 코드 발급·폐기·차단·한도 조정 및 감사 조회

- [ ] **Step 1: 일반 사용자의 관리자 API 접근 거부와 관리자 변경 감사 테스트를 작성한다.**
- [ ] **Step 2: 원문 코드를 한 번만 보여주는 보호된 발급 API와 최소 관리 화면을 구현한다.**
- [ ] **Step 3: 검증된 새 Google 신원의 이전 요청을 관리자만 승인하고 기존 account·owner·쿼터를 유지하며 이전 세션을 폐기하는 흐름을 구현한다.**
- [ ] **Step 4: `이 대화 남은 메시지`와 `계정 남은 AI 요청`을 분리 표시한다.**
- [ ] **Step 5: 연속 클릭·429·비활성화 상태 UI를 검증한다.**
- [ ] **Step 6: 사용자 검수 후 main 반영·실행본·CI를 확인한다.**

### Task 5: 통합·운영 안전 검증

**Files:**
- Create: `backend/tests/test_invite_demo_flow.py`
- Modify: `.env.example`, `README.md`, deployment documentation

**Interfaces:**
- Consumes: Tasks 1–4 전체 계약
- Produces: 약 10명 제한 데모의 배포 전 검증표와 운영 절차

- [ ] **Step 1: Google 로그인→초대 코드 등록→대화/개인용어→차감→차단/로그아웃 전체 흐름을 격리 환경에서 검증한다.**
- [ ] **Step 2: 계정·IP 속도 제한과 전역 운영 안전한도를 승인된 숫자로 적용한다.**
- [ ] **Step 3: 키·쿠키·PII 로그와 타 계정 데이터 격리를 점검한다.**
- [ ] **Step 4: 운영 DB 백업·비파괴 migration·롤백 리허설 후 별도 승인으로 배포한다.**
- [ ] **Step 5: 실제 Google OAuth 설정과 초대 코드는 사용자의 별도 승인 후에만 생성한다.**
