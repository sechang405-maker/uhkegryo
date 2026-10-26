# Invite Demo Auth and Quota Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 약 10명의 초대 사용자가 Google 로그인 후 계정별 누적 AI 요청 한도 안에서 어케그려를 사용하도록 한다.

**Architecture:** FastAPI가 Google OIDC와 불투명 앱 세션을 소유하고 PostgreSQL 계정을 기존 `owner_id`에 연결한다. AI 호출 직전 원자적으로 1회를 예약하고 성공 결과 저장 후 확정하며, 실패·중복·내부 재시도는 같은 원장을 재사용하거나 해제한다. 기존 대화별 20회 제한은 별도로 유지한다.

**Tech Stack:** FastAPI, PostgreSQL/asyncpg, Next.js 16, Google OIDC, 기존 OpenRouter·SearXNG

**Spec:** `docs/superpowers/specs/2026-10-26-invite-demo-auth-quota-design.md`

## Global Constraints

- Google이 검증한 초대 이메일만 로그인할 수 있다.
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
- OAuth 콜백 재전송·초대 취소·이메일 변경: 계정 중복이나 권한 우회가 없어야 한다(Task 2).
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
- Create: `backend/routes/auth.py`
- Create: `backend/db/migrations/010_auth_sessions.sql`
- Modify: `backend/main.py`, `backend/shared/config.py`, `frontend/app/page.jsx`
- Test: `backend/tests/test_google_auth.py`, `backend/tests/test_auth_sessions.py`

**Interfaces:**
- Consumes: `DemoAccountRepository.accept_invite()`와 account → owner 연결
- Produces: `/api/auth/google/start`, callback, `/api/auth/me`, `/api/auth/logout`

- [ ] **Step 1: state·nonce·PKCE, issuer/audience/서명/만료, 검증 이메일, 초대·차단 실패 테스트를 작성한다.**
- [ ] **Step 2: standards-compliant OIDC client와 해시된 불투명 앱 세션을 구현한다.**
- [ ] **Step 3: 모든 owner-scoped API가 앱 세션의 account → owner만 신뢰하도록 전환한다.**
- [ ] **Step 4: 기존 익명 로컬 모드는 명시적 개발 설정에서만 유지하고 자동 병합이 없음을 검증한다.**
- [ ] **Step 5: 사용자 검수 후 main 반영·실행본·CI를 확인한다.**

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
- Produces: 사용자 잔여 AI 횟수, 관리자 초대·차단·한도 조정 및 감사 조회

- [ ] **Step 1: 일반 사용자의 관리자 API 접근 거부와 관리자 변경 감사 테스트를 작성한다.**
- [ ] **Step 2: 보호된 관리 API와 최소 관리 화면을 구현한다.**
- [ ] **Step 3: `이 대화 남은 메시지`와 `계정 남은 AI 요청`을 분리 표시한다.**
- [ ] **Step 4: 연속 클릭·429·비활성화 상태 UI를 검증한다.**
- [ ] **Step 5: 사용자 검수 후 main 반영·실행본·CI를 확인한다.**

### Task 5: 통합·운영 안전 검증

**Files:**
- Create: `backend/tests/test_invite_demo_flow.py`
- Modify: `.env.example`, `README.md`, deployment documentation

**Interfaces:**
- Consumes: Tasks 1–4 전체 계약
- Produces: 약 10명 제한 데모의 배포 전 검증표와 운영 절차

- [ ] **Step 1: 초대→로그인→대화/개인용어→차감→차단/로그아웃 전체 흐름을 격리 환경에서 검증한다.**
- [ ] **Step 2: 계정·IP 속도 제한과 전역 운영 안전한도를 승인된 숫자로 적용한다.**
- [ ] **Step 3: 키·쿠키·PII 로그와 타 계정 데이터 격리를 점검한다.**
- [ ] **Step 4: 운영 DB 백업·비파괴 migration·롤백 리허설 후 별도 승인으로 배포한다.**
- [ ] **Step 5: 실제 Google OAuth 설정과 초대 계정은 사용자의 별도 승인 후에만 생성한다.**
