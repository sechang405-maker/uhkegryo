# 작업 티켓 — UH케그려

## 작업 번호와 GitHub PR 매핑

| 작업 번호 | GitHub PR |
| --- | --- |
| 작업 1 | GitHub PR #38 |
| 작업 2 | GitHub PR #39 |
| 작업 3 | GitHub PR #40 |
| 작업 4 | GitHub PR #41 |
| 작업 5 | GitHub PR #42 |
| 작업 6 | GitHub PR #43 |
| 작업 7 | GitHub PR #44 |
| 작업 8 | GitHub PR #45 |
| 작업 9 | GitHub PR #46 |
| 작업 10 | GitHub PR #47 |
| 작업 11 | GitHub PR #48 |
| 작업 12 | GitHub PR #49 |
| 작업 13 | GitHub PR #50 |
| 작업 14 | GitHub PR #51 |
| 작업 15 | GitHub PR #52 |
| 작업 16 | GitHub PR #53 |
| 작업 17 | GitHub PR #54 |
| 작업 18 | GitHub PR #55 |
| 작업 19 | GitHub PR #56 |
| 작업 20 | GitHub PR #57 |
| 작업 21 | GitHub PR #58 |
| 작업 22 | GitHub PR #59 |
| 작업 23 | GitHub PR #60 |
| 작업 24 | GitHub PR #61 |



## 계획 기준

- 기준 브랜치: `main`
- 원칙: GitHub PR 1개 = 브랜치 1개
- GitHub PR 변경량: 400줄 이하
- 브랜치 생성: 최신 `main`에서만 생성
- 브랜치 형식: `{이니셜}{번호}/{작업유형}/{짧은-영문-설명}`
- 아래 브랜치명은 작업 식별용 예시이며, 실제 생성 시 해당 팀원의 사용 이력을 다시 조회해 다음 번호로 확정한다.
- 구현 전 관련 `docs/specs/{feature-name}.md`의 Why, Goal, What, How, AC를 완성한다.
- AC 기반 테스트 통과 후에만 완료로 표시한다.
- GitHub PR 승인 후 사람이 merge한다.

## 현재 구현 현황 (2026-10-03 근거 정리)

| 영역 | 상태 | 근거·다음 작업 |
| --- | --- | --- |
| FastAPI·cookie·PostgreSQL 세션/Job | 구현됨 | routes·repository·migration, 최종 운영 검증 필요 |
| worker·retry·lease recovery | 구현됨 | agent_worker·job_retry_recovery |
| TERM_CARD·resolver·응답 계약 | 구현됨 | 활성 카드 검증·Pydantic·결정론 조립 |
| OpenRouter·v4 해석 | 구현됨 | 이전 작업 트리 참고 30/30 + 10/10; 현재 PR 지문 불일치, 재평가 필요 |
| MCP 검색·SearXNG·widget | 구현됨 | 후보 ddd7f93 실제 Pin 16개 연결 검증; 최종 main E2E 필요 |
| Next.js 결과·대화 UI | 구현됨 | frontend/app/page.jsx·ConversationPanel; 운영 브라우저 검증 필요 |
| Langfuse 수신·전환 | PR #108 병합됨 | 공용·로컬 합성 trace 검증; 실제 요청 관측 필요 |
| 원격 Prompt·Dataset·정성 평가 | 미완료 | 파일 로딩과 자동 기대값 검사를 구분 |
| 평가 리포트 | 기존 증거 정리됨 | EVAL_REPORT.md; 운영 지표·정성 점수·최종 비교 추가 필요 |
| 사용자 배포·영상·스크린샷 | 미완료 | 실제 URL·정상/실패 화면·운영 trace 확보 |

아래 번호별 티켓은 원래 작업 분할 계획이다. 완료 상태는 이 표와 EVAL_REPORT.md를 우선하며, 과거의 mock·골조 표기를 현재 기능 상태로 해석하지 않는다.

## 완료된 작업

다음 항목은 현재 `main`에 반영되어 있으므로 다시 구현하지 않는다.

| 작업 | 상태 |
| --- | --- |
| TERM_CARD loader와 시작 fail-closed 검증 | ✅ 완료 |
| FastMCP `get_active_term_card`와 `/mcp` 서버 골조 | ✅ 완료 |
| 세션 쿠키 발급·재사용·90일 갱신 골조 | ✅ 완료 |
| 인메모리 mock `POST /api/agent` 골조 | ✅ 완료 |
| 인메모리 mock `GET /api/jobs/{job_id}` polling 골조 | ✅ 완료 |
| API Pydantic 계약·resolver·응답 조립 | ✅ 완료 |
| 검색 URL builder와 `drawing` 접미사 계약 테스트 | ✅ 완료 |
| OpenRouter LLM adapter 골조와 구조화 출력 검증 | ✅ 완료 |
| LLM generation observation 일부 | 🟡 부분 구현, 운영 검증 미완료 |

## 남은 작업: 작업 번호별 세부 티켓

### 데이터 저장

#### 작업 1 · DB 설정과 migration 기반

- 브랜치: `feature/postgres-migration-foundation`
- Spec: `docs/specs/session-job-persistence.md`
- 작업: DB 설정과 migration 실행 기반을 추가한다. migration은 파일명 순으로 실행하고 `schema_migrations(version, applied_at)`에 적용 이력을 남기며, 적용과 이력 기록을 하나의 transaction으로 처리한다.
- 제외: Repository, route 교체, worker.
- AC (Given-When-Then): GIVEN 미적용 migration이 있을 때 WHEN migration runner를 실행하면 THEN 미적용 SQL과 이력을 transaction으로 적용하고, 재실행 시에는 이미 적용한 파일을 건너뛴다. GIVEN migration SQL이 실패할 때 WHEN transaction이 rollback되면 THEN 이력이 남지 않는다.
- 의존성: `docs/specs/api-contract.md`
- 파일 범위: `.env.example`, `DEPLOYMENT.md`, `scripts/gcp-setup-free.sh`, `backend/shared/config.py`, `backend/shared/database.py`, `backend/db/migrate.py`, migration 디렉터리, DB 설정·migration 테스트만 수정한다.
- 예상 변경량: 150줄 이하

#### 작업 2 · Session Repository

- 브랜치: `feature/session-repository`
- Spec: `docs/specs/session-repository.md`
- 작업: session 생성·조회·활동 갱신·토큰 hash 조회·3개월 초과 비활성 session 삭제만 구현한다. 빈 token은 DB 호출 전에 거부하고, 미등록 token은 `None`을 반환하며, DB 오류는 호출자에게 전달한다.
- AC (Given-When-Then): GIVEN 유효한 token이 있을 때 WHEN session을 생성·조회하면 THEN token hash만 저장하고 조회 시 `last_activity_at`을 갱신한다. GIVEN 빈 token 또는 미등록 token일 때 WHEN 조회·생성하면 THEN 각각 DB 호출 전 `ValueError` 또는 `None`을 반환한다.
- 의존성: 작업 1
- 파일 범위: `backend/services/session_repository.py`, `backend/tests/test_session_repository.py`, `docs/specs/session-repository.md`만 수정한다.
- 예상 변경량: 250줄 이하

#### 작업 3 · Job Repository와 idempotency

- 브랜치: `feature/job-repository-idempotency`
- Spec: `docs/specs/session-job-persistence.md`
- 작업: Job 저장·조회·상태 갱신·동일 키 재사용·충돌 판정.
- AC (Given-When-Then): GIVEN 같은 세션에서 요청이 재전송될 때 WHEN 키와 원문이 같으면 THEN 기존 Job을 반환하고 원문이 다르면 충돌시킨다.
- 의존성: 작업 1, 작업 2
- 파일 범위: Job repository, idempotency 모델, repository 테스트만 수정한다.
- 예상 변경량: 300줄 이하

#### 작업 4 · API 저장소 교체

- 브랜치: `feature/postgres-agent-routes`
- Spec: `docs/specs/api-contract.md`, `docs/specs/session-job-persistence.md`
- 작업: `POST /api/agent`, `GET /api/jobs/{job_id}`를 PostgreSQL Repository에 연결한다.
- AC (Given-When-Then): GIVEN 유효한 Agent 요청이 있을 때 WHEN API가 저장소를 호출하면 THEN 쿠키 소유권·404 위장·90일 갱신·queued 응답을 유지한다.
- 의존성: 작업 2, 작업 3
- 파일 범위: `backend/routes/agent.py`와 route 테스트만 수정한다.
- 예상 변경량: 250줄 이하

#### 작업 5 · 세션 retention cleanup

- 브랜치: `feature/session-retention-cleanup`
- Spec: `docs/specs/session-job-persistence.md`
- 작업: 3개월 비활성 session과 연결 Job을 정리한다.
- AC (Given-When-Then): GIVEN 만료된 session이 있을 때 WHEN cleanup을 실행하면 THEN 연결 Job과 원문도 함께 삭제된다.
- 의존성: 작업 2, 작업 3
- 파일 범위: retention task와 cleanup 테스트만 수정한다.
- 예상 변경량: 180줄 이하

### Worker

#### 작업 6 · Job claim transaction

- 브랜치: `feature/job-claim-transaction`
- Spec: `docs/specs/postgres-job-worker.md`
- 작업: queued Job claim, attempt 증가, lease 기록.
- AC (Given-When-Then): GIVEN 같은 queued Job에 동시 claim이 발생할 때 WHEN 두 worker가 실행되면 THEN 하나만 claim한다.
- 의존성: 작업 3
- 파일 범위: claim repository 메서드와 동시성 테스트만 수정한다.
- 예상 변경량: 300줄 이하

#### 작업 7 · Worker 상태 전이

- 브랜치: `feature/job-state-machine`
- Spec: `docs/specs/postgres-job-worker.md`, `docs/specs/api-contract.md`
- 작업: validating/searching/rendering과 completed/failed 전이를 구현한다.
- AC (Given-When-Then): GIVEN 현재 상태와 허용되지 않은 다음 상태가 주어질 때 WHEN 전이를 시도하면 THEN 거부하고 종결 payload는 계약대로 저장한다.
- 의존성: 작업 6
- 파일 범위: 상태 전이 함수와 상태 전이 테스트만 수정한다.
- 예상 변경량: 250줄 이하

#### 작업 8 · 자동 재시도와 lease recovery

- 브랜치: `feature/job-retry-recovery`
- Spec: `docs/specs/postgres-job-worker.md`
- 작업: `next_retry_at`, 최대 3회 재시도, lease 만료 복구.
- AC (Given-When-Then): GIVEN 오류가 발생할 때 WHEN worker가 오류를 분류하면 THEN 재시도 가능 오류만 예약하고 최대 3회에서 종료한다.
- 의존성: 작업 6, 작업 7
- 파일 범위: retry/recovery worker와 retry 테스트만 수정한다.
- 예상 변경량: 300줄 이하

#### 작업 9 · Worker Agent pipeline 연결

- 브랜치: `feature/worker-agent-pipeline`
- Spec: `docs/specs/api-contract.md`, `docs/specs/prompt-interpreter-v0.md`
- 작업: 저장 Job을 LLM adapter → resolver → 응답 조립으로 실행한다.
- AC: success, clarification, partial, terminal failure를 계약대로 저장한다.
- 의존성: 작업 4, 작업 6, 작업 7, 작업 8

### Pinterest

#### 작업 10 · Provider 계약과 fake provider

- 브랜치: `feature/pinterest-provider-contract`
- Spec: `docs/specs/pinterest-widget-crawler.md`
- 작업: provider 인터페이스, 결과 타입, fake provider와 계약 테스트.
- AC (Given-When-Then): GIVEN fake provider 결과가 있을 때 WHEN 결과를 조립하면 THEN `pin_id`, `pin_url`, `status`를 만족한다.
- 의존성: 없음
- 파일 범위: provider protocol, 결과 타입, fake provider 테스트만 수정한다.
- 예상 변경량: 220줄 이하

#### 작업 11 · 서버 공개 검색 수집

- 브랜치: `feature/pinterest-public-search`
- Spec: `docs/specs/pinterest-widget-crawler.md`
- 작업: 서버 Playwright 공개 검색과 Pin ID·URL 추출.
- AC (Given-When-Then): GIVEN 서버 검색이 실행될 때 WHEN provider가 요청을 만들면 THEN Pinterest API v5와 브라우저 직접 호출을 사용하지 않는다.
- 의존성: 작업 10
- 파일 범위: 서버 검색 adapter와 fixture parser 테스트만 수정한다.
- 예상 변경량: 350줄 이하

#### 작업 12 · Widget 결과 조립

- 브랜치: `feature/pinterest-widget-results`
- Spec: `docs/specs/pinterest-widget-crawler.md`
- 작업: widget 조회, deleted 처리, 역할별 8개 제한, 원순서 보존.
- AC (Given-When-Then): GIVEN widget 응답에 thumbnail이 있을 때 WHEN 결과를 반환하면 THEN 현재 응답에만 포함하고 저장·trace·로그에는 남기지 않는다.
- 의존성: 작업 10, 작업 11
- 파일 범위: widget adapter, 결과 조립기, 개인정보 비저장 테스트만 수정한다.
- 예상 변경량: 350줄 이하

#### 작업 13 · Worker 검색 단계 연결

- 브랜치: `feature/worker-pinterest-search`
- Spec: `docs/specs/api-contract.md`, `docs/specs/pinterest-widget-crawler.md`
- 작업: 검색 provider 호출과 reason code 조립.
- AC: `PIN_RESULTS_EMPTY`와 `PIN_SEARCH_UNAVAILABLE`을 구분한다.
- 의존성: 작업 9, 작업 12

### 관측·보안

#### 작업 14 · Trace 필수 필드

- 브랜치: `feature/trace-required-fields`
- Spec: `docs/specs/observability-and-prompt-versioning.md`
- 작업: job/session/attempt/model/prompt version을 trace에 기록한다.
- AC: 세션 토큰 원문·thumbnail URL·secret이 trace에 없다.
- 의존성: 작업 9

#### 작업 15 · 실패 코드·사용자 메시지 매핑

- 브랜치: `feature/failure-code-mapping`
- Spec: `docs/specs/api-contract.md`
- 작업: LLM·검색·DB·worker 예외를 공개 FailureCode로 매핑한다.
- AC: 내부 오류 원문과 secret이 `user_message`에 노출되지 않는다.
- 의존성: 작업 9, 작업 13

#### 작업 25 · Input safety gate

- 브랜치: `feature/input-safety-gate`
- Spec: `docs/specs/input-safety-gate.md`, `docs/specs/trust-boundary.md`, `docs/specs/api-contract.md`
- 작업: worker의 `validating` 단계에서 프롬프트 지시 덮어쓰기, 비밀·타인 데이터 추출, 유해·불법 실행 요청을 판정하고 `unsafe_input`으로 종결한다. literal 그림 문맥 예외는 해당 구간에만 적용한다. `needs_clarification`의 사용자 질문은 LLM 문구를 전달하지 않고 서버가 조립하며, resolver는 evidence가 원문에 실제로 있는지 재검증한다.
- AC: unsafe 입력은 `completed + UNSAFE_INPUT`을 저장하고 LLM·resolver·Pinterest 검색을 호출하지 않는다. 정상 일러스트 요청은 기존 pipeline을 유지하며, LLM 생성 질문과 원문에 없는 evidence는 사용자 응답에 포함되지 않는다.
- 의존성: 작업 9
- 파일 범위: `backend/services/input_safety.py`, `backend/services/agent_worker.py`, `backend/services/job_repository.py`, `backend/services/resolver.py`, `backend/services/response_assembler.py`, 해당 pytest, `prompts/uhkegryo-interpreter-v0.md`, 관련 API·prompt·input-safety Spec과 작업 티켓만 수정한다.
- 예상 변경량: 코드·테스트 300줄 이하

#### 작업 16 · 외부 MCP client 증거

- 브랜치: `test/mcp-client-evidence`
- Spec: `docs/specs/mcp-contract.md`
- 작업: 외부 MCP client 호출 절차와 결과 증거를 기록한다.
- AC: 접근 제어와 도구 응답을 재현할 수 있다.
- 의존성: 기존 `backend/mcp/` 구현
- 파일 범위: MCP 호출 증거 문서와 검증 스크립트만 수정한다.
- 예상 변경량: 200줄 이하

### UI

#### 작업 17 · Next.js UI Spec

- 브랜치: `docs/nextjs-agent-ui-spec`
- 작업: UI 전용 Spec을 만들고 Why, Goal, What, How, AC를 완성한다.
- 범위: 입력, polling, 완료, clarification, partial, failure 상태.
- 의존성: `docs/specs/api-contract.md`
- Spec: 이 PR에서 생성하는 `docs/specs/nextjs-agent-ui.md`
- AC: Given 유효한 입력, When 사용자가 제출, Then 요청·polling·종결 상태별 화면 계약이 문서에 Given-When-Then으로 정의된다.
- 파일 범위: `docs/specs/nextjs-agent-ui.md`만 생성한다.
- 예상 변경량: 250줄 이하

#### 작업 18 · UI 입력과 요청 제출

- 브랜치: `feature/nextjs-agent-input`
- Spec: `docs/specs/nextjs-agent-ui.md`
- 작업: 1~500자 입력, Idempotency-Key, 동일 origin `/api` 호출.
- AC: 유효성 오류가 API 호출 전에 표시된다.
- 의존성: 작업 17, `docs/specs/nextjs-agent-ui.md`

#### 작업 19 · UI Job polling

- 브랜치: `feature/nextjs-job-polling`
- Spec: `docs/specs/nextjs-agent-ui.md`
- 작업: queued/running/completed/failed 표시와 polling 종료.
- AC: 종결 상태에서 polling을 중단한다.
- 의존성: 작업 17, 작업 18

#### 작업 20 · UI 결과·질문·Pin 링크

- 브랜치: `feature/nextjs-agent-results`
- Spec: `docs/specs/nextjs-agent-ui.md`
- 작업: 용어 설명, 질문, 부분 결과, 원본 Pin 링크와 thumbnail 표시.
- AC: thumbnail URL을 저장값처럼 다루지 않는다.
- 의존성: 작업 17, 작업 19, 작업 13

### 평가·출시

#### 작업 21 · 계약 평가 실행기

- 브랜치: `test/contract-evaluation-runner`
- Spec: `docs/specs/contract-evaluation-variants.md`
- 작업: 원문 30건·변형 70건 실행과 계약 위반 집계.
- AC (Given-When-Then): GIVEN 동일 평가셋이 있을 때 WHEN 평가 실행기를 실행하면 THEN 성공률과 실패 유형을 동일한 형식으로 산출한다.
- 의존성: 작업 9, 작업 13, 작업 15
- 파일 범위: `evals/run_evals.py`와 평가 실행 테스트만 추가한다.
- 예상 변경량: 350줄 이하

#### 작업 22 · 성능·비용 측정

- 브랜치: `test/performance-cost-measurement`
- Spec: `docs/specs/observability-and-prompt-versioning.md`
- 작업: p50/p95 지연, 요청당 비용, retry 비율을 측정한다.
- AC (Given-When-Then): GIVEN 평가 실행 결과가 있을 때 WHEN 측정 명령을 다시 실행하면 THEN 동일 평가셋 기준의 지연·비용 결과를 재현한다.
- 의존성: 작업 21, 작업 14
- 파일 범위: 측정 스크립트와 측정 결과 schema 테스트만 추가한다.
- 예상 변경량: 300줄 이하

#### 작업 23 · EVAL_REPORT와 출시 게이트

- 브랜치: `docs/release-gate-report`
- 작업: 평가·관측·비용·실패 사례·출시 판정을 기록한다.
- AC: 모든 기준을 통과/미통과로 명시한다.
- Spec: `docs/SCAFFOLD.md`, `docs/specs/observability-and-prompt-versioning.md`
- 의존성: 작업 21, 작업 22

#### 작업 24 · 배포·데모 증거

- 브랜치: `test/deployment-demo-evidence`
- 작업: Cloud Run API, UI URL, MCP client, 정상·실패 데모 증거를 기록한다.
- AC: 실제 날짜·URL·모델·prompt version만 기록한다.
- Spec: `DEPLOYMENT.md`, `docs/specs/mcp-contract.md`
- 의존성: 작업 16, 작업 20, 작업 23

## 의존 순서

```text
작업 1 → 작업 2 → 작업 3 → 작업 4 → 작업 5
                         ↓
        작업 6 → 작업 7 → 작업 8 → 작업 9
                                   ↓
        작업 10 → 작업 11 → 작업 12 → 작업 13
                                   ↓
        작업 14 → 작업 15 → 작업 16
                                   ↓
        작업 17 → 작업 18 → 작업 19 → 작업 20
                                   ↓
        작업 21 → 작업 22 → 작업 23 → 작업 24
```

작업 14과 작업 17는 계약이 확정되면 병렬로 시작할 수 있다. UI 구현은 작업 17 Spec이 먼저 merge된 뒤 시작한다.


## 작업 완료 체크리스트

- [ ] 변경량 400줄 이하
- [ ] 이 작업의 목적과 파일 범위가 다른 티켓과 겹치지 않음
- [ ] 기능 코드 변경 시 해당 AC를 검증하는 테스트가 함께 포함됨
- [ ] 관련 Spec의 AC 테스트 통과
- [ ] `NOT_BUILD.md` 범위 미침범
- [ ] 무관한 파일 미수정
- [ ] secret·세션 토큰·외부 이미지 바이트 미커밋
- [ ] GitHub PR 승인 후 사람이 merge
- [ ] merge 후 해당 티켓을 `✅ 완료`로 갱신

## 의도적으로 만들지 않는 기능

- 이미지 생성·편집·업로드 이미지 분석
- 특정 작가 화풍 복제
- 외부 어휘 API·Getty 런타임 호출
- Pinterest 이미지 파일·thumbnail·본문 저장
- 자동 TERM_CARD 생성·수정
- RAG 및 카드 밖 텍스트의 LLM prompt 주입
- 사용자 retry endpoint
