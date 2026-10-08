# 팀 운영 배포 — Vercel·Cloud Run API/worker

팀 프로젝트 기간의 실제 서비스 운영 계약이다. 개인별 종료 후 공개 방식은 [개인 포트폴리오 배포](./personal-portfolio-deployment.md)를 따른다. 기존 파일 경로는 참조 호환을 위해 유지한다.

## Why

- **페르소나**: UH케그려 데모를 운영하는 팀원과 브라우저로 접속하는 일러스트 초보자.
- **상황**: 로컬 Next.js·FastAPI 실행 없이 공개 HTTPS 주소에서 입력, job 결과, 대화 이력을 이용한다.
- **문제**: 프론트엔드만 배포하면 backend에 연결되지 않는다. 현재 worker는 `backend.main:app` lifespan에서 시작되므로 Cloud Run이 요청 외 CPU를 제한하거나 인스턴스를 0개로 줄이면 DB job 처리가 멈출 수 있다.
- **측정 지표**: 배포 브라우저 E2E 성공 건수, 요청 없는 상태의 job 완료 여부, 재시작 후 lease 복구 여부, 세션 소유권 검증 결과.

## Goal

- Vercel에 `frontend`를 배포하고, 기존 Cloud Run API 서비스 내부 worker가 PostgreSQL job을 계속 처리하도록 설정한다.
- 운영 시작일·종료 예정일, 비용 부담자, GCP 결제 계정, 예산, 종료 담당자를 배포 기록에 명시한다. 개인 포트폴리오에 공용 backend를 계속 제공하는 것은 기본 운영 범위에 포함하지 않는다.
- 정상 외부 의존성을 갖춘 Preview에서 서로 다른 브라우저 세션의 유효 입력 3건 모두 `202` 응답 후 300초 이내 `completed`에 도달하고 결과 UI를 표시한다. 이는 배포 승인용 smoke 기준이며 서비스 SLA가 아니다.
- HTTP 요청을 중단한 상태에서도 제출한 job이 종결되고, 재시작 후 lease 복구와 세션 소유권 AC를 모두 통과한다.
- **Out of Scope**: 별도 worker 서비스/worker pool 분리, Cloud Tasks/Pub/Sub 도입, 큐·API·쿠키 계약 변경, UI 기능 추가, 모델 교체, 신규 MCP·Langfuse 플랫폼 구축, 도메인 구매, GitHub commit/push/PR 및 실제 운영 배포 승인.
- 이 변경은 배포 계약 작성이다. 구현과 외부 검증이 끝나기 전 배포 기능 완료로 보고하지 않는다.

## What

**Happy Path**
1. 운영자가 대상 GCP project, 기존 API/MCP 서비스, Neon DB, Langfuse 프로젝트와 Vercel 프로젝트를 선택한다.
2. 대상 DB migration을 명시적으로 실행한 뒤 Cloud Run API와 MCP 연결을 준비한다.
3. API 컨테이너 시작 시 카탈로그 검증과 worker 시작이 이루어진다.
4. Vercel Preview를 생성하고 브라우저는 동일 origin의 `/api/*`를 호출한다.
5. Next.js rewrite가 Cloud Run API로 요청을 전달하고 세션 쿠키와 응답을 브라우저에 반환한다.
6. worker는 DB job을 처리하며 UI는 polling으로 결과와 대화 이력을 표시한다.
7. Preview AC를 통과한 동일 commit의 운영 환경을 검증하고 Production 배포를 승인한다.
8. 팀 운영 종료 시 개인 데모 전환을 확인하고, 승인된 공용 리소스 종료 절차를 수행한다.

**Edge Cases**

| 상황 | 처리 방식 |
| --- | --- |
| `AGENT_API_ORIGIN` 누락 또는 로컬 주소 | 배포 사전 검사 실패. 운영에서 로컬 기본값을 사용하지 않는다. |
| DB migration 누락·DB 연결 실패 | 배포 승인을 중단하고 migration/연결을 수정한다. `/health` 성공만으로 DB·worker 정상이라고 판단하지 않는다. |
| 카탈로그 또는 프롬프트 설정 오류 | 배포 승인을 중단한다. 카탈로그는 기존 시작 검증, 프롬프트는 adapter 초기화 검증을 따른다. |
| HTTP 요청이 없는 상태 | 최소 인스턴스와 instance-based billing으로 worker 실행을 유지한다. 주기적 HTTP 호출을 유지 수단으로 사용하지 않는다. |
| revision 교체·인스턴스 종료 | 실행 중 job은 기존 lease 만료·attempt fencing 계약으로 복구한다. 외부 LLM 요청의 중복 실행 가능성은 있으며 exactly-once를 주장하지 않는다. |
| MCP IAM 거부·검색/LLM 장애 | 기존 failure 및 partial result 계약을 따른다. MCP를 공개로 전환하지 않는다. |
| Preview와 Production DB 혼용 | Preview에는 별도 Neon branch와 별도 API/MCP 서비스를 사용한다. 운영 DB를 Preview의 쓰기 대상으로 사용하지 않는다. |
| Vercel 환경변수 변경 | 재배포 후 rewrite 대상과 실제 응답을 재검증한다. |
| 배포 후 회귀 | 이전 Vercel deployment와 호환 가능한 Cloud Run revision으로 되돌린다. DB migration을 자동 역실행하지 않는다. |
| 종료일 연장 | 비용 부담자의 명시적 동의와 새 종료일을 기록한다. 공용 backend 유지 기간을 자동 연장하지 않는다. |
| 공용 리소스가 다른 프로젝트와 공유됨 | 소유자와 사용처를 확인하고 이 팀 전용 리소스만 정리한다. 공유 리소스는 삭제하지 않고 남은 비용·담당자를 기록한다. |

## How

### 기존 계약과 실행 구조

- 제품 범위는 `../PRD.md`, 아키텍처는 `../SDD.md`를 따른다.
- endpoint와 응답·오류는 `api-contract.md`, 세션은 `session-cookie-token.md`, job 처리·lease·재시도는 `postgres-job-worker.md`가 단일 기준이다.
- `POST /api/agent`는 `202 + job_id`, `GET /api/jobs/{job_id}`는 같은 세션 소유 job 상태/결과를 반환한다. 대화 API와 용어 검색도 기존 `/api/*` 경로를 유지한다.
- 신규 endpoint, Route Handler BFF, 별도 worker 진입점은 만들지 않는다. API와 worker는 기존 `uvicorn backend.main:app --host 0.0.0.0 --port 8000` 프로세스를 공유한다.
- `/health`는 기존 응답 `{"status":"ok"}`를 유지하며 worker 진행 여부는 실제 DB job 종결로 검증한다.

### Vercel

#### 기존 공개 주소 갱신

- 이 절은 공개 alias 갱신의 공통 절차다. 날짜별 GCP 주소 재연결 기록은 Vercel 설정 뒤에 별도로 보존하고, 해당 기록의 deployment ID 확인·복구는 이 절차를 따른다.
- 사용자가 지정한 공개 주소: **https://uhkegryo.vercel.app/**.
- 기존 프로젝트: `uhkegryo-team-preview`, project ID `prj_QKEYbMeTdXkvdP3kNXdsslEmy7hy`, account ID `team_46jAJPAj5m0xLdxRiAI0hyxo`.
- 2026-10-06 확인: 공개 주소는 이전 deployment에 별도로 지정된 alias였다. 같은 프로젝트의 Production을 배포해도 이 alias가 이전 deployment에 남아 있어 명시적으로 갱신했다.
- 배포 전 공개 주소가 가리키는 deployment ID와 project ID를 조회하고 이전 deployment ID를 복구용으로 기록한다. 로컬 `.vercel/project.json`의 프로젝트명이나 생성된 배포 URL만으로 대상 주소를 판단하지 않는다.
- 기존 프로젝트에 요청된 commit을 배포하고 `READY`를 확인한 뒤, 새 deployment에 `uhkegryo.vercel.app` alias를 연결한다. CLI 인증이 있으면 아래 명령을 사용한다. `<new-deployment-url>`은 해당 배포 결과로 바꾼다.

```bash
vercel alias set <new-deployment-url> uhkegryo.vercel.app
vercel inspect https://uhkegryo.vercel.app
```

- Vercel 연결 도구를 쓰면 `vercel_assign_alias`의 `id`에 새 deployment ID, `requestBody.alias`에 `uhkegryo.vercel.app`을 전달한다. 이후 `vercel_get_deployment`의 `idOrUrl`을 `uhkegryo.vercel.app`으로 조회해 새 deployment ID와 일치하는지 확인한다.
- 공개 주소에서 페이지 HTTP 200, 최신 빌드 asset 일치, same-origin API 정상 응답을 검증하고 완료 보고에는 **https://uhkegryo.vercel.app/**를 제공한다. 생성된 deployment URL은 진단용으로만 기록한다.
- Git 자동 배포가 차단되면 기존 프로젝트에 로컬 소스를 직접 업로드할 수 있다. 비밀 파일은 제외하고 실제 commit 출처를 유지한다. 권한이 없으면 사용자에게 접근 문제를 알린다. 별도 승인 없이 새 프로젝트 생성이나 다른 공개 주소로 대체하지 않는다.

| 항목 | 계약 |
| --- | --- |
| Framework Preset | Next.js |
| Root Directory | `frontend` |
| Install / Build | `npm ci` / `npm run build` |
| Output Directory | Next.js 기본값 |
| Node.js | Vercel에서 지원하는 22.x, 로컬 검증도 같은 major 사용 |
| Root 외부 파일 | 현재 `turbopack.root`가 저장소 root를 가리키므로 외부 파일 포함 옵션 활성화 |
| `NEXT_PUBLIC_API_BASE_URL` | `/api` |
| `NEXT_PUBLIC_UI_DEMO` | `0` |
| `AGENT_API_ORIGIN` | 환경별 Cloud Run API HTTPS origin, 경로·query 없이 지정 |

- `frontend/next.config.mjs`의 `/api/:path*` → `${AGENT_API_ORIGIN}/api/:path*` rewrite를 유지한다.
- 브라우저는 `credentials: "include"`와 same-origin API를 사용한다. backend origin 직접 호출은 사용하지 않는다.
- API의 `Set-Cookie`가 프록시를 거쳐 전달되어 `session_id`에 HttpOnly, Secure, SameSite=Lax, Path=/ 및 달력 기준 3개월 만료가 적용되어야 한다. Domain을 별도 설정하지 않는다.
- API key, DB URL, Langfuse secret을 Vercel 또는 `NEXT_PUBLIC_*`에 넣지 않는다.
- `.vercelignore`로 `.env*`와 비밀키·backend 배포 소스를 업로드 대상에서 제외한다. Vercel CLI dry run으로 실제 업로드 목록에 환경파일이 0개인지 검증한다. `.vercel` 연결 정보는 Git에서 제외한다.

#### 2026-10-06 GCP 주소 재연결

- 기존 공개 주소와 프로젝트를 유지한다. 현재 조회한 API origin은 `https://api-fgdrdxsn6q-du.a.run.app`, MCP endpoint는 `https://mcp-fgdrdxsn6q-du.a.run.app/mcp`다.
- 이 재연결 절차와 공개 주소 검증의 대상은 Production이다. Production `AGENT_API_ORIGIN`을 위 API origin으로 갱신하고 `NEXT_PUBLIC_API_BASE_URL=/api`, `NEXT_PUBLIC_UI_DEMO=0`을 적용한다. 기존 프런트엔드 배포 소스를 재빌드하고 READY 이후 공개 alias를 연결한다.
- Preview에는 별도 API/MCP 서비스와 별도 Neon branch를 사용한다. 위 Production API origin을 Preview 설정에 복사하지 않으며, 이 공개 주소 smoke로 Preview 격리 검증을 통과했다고 판단하지 않는다.
- API의 `MCP_BASE_URL`과 MCP의 `MCP_ALLOWED_HOST`가 실제 MCP 주소와 일치하면 변경하지 않는다. 신규 서비스 생성, DB migration, backend 이미지 교체는 이 주소 재연결 범위에 포함하지 않는다.
- Given 재연결한 공개 주소, When 페이지와 쿠키 없는 `/api/sessions`를 조회, Then 페이지 200 및 backend 계약의 JSON 401 `session_required`가 반환된다.
- Given 공개 주소에서 새 대화를 생성, When 같은 쿠키로 대화 목록을 조회, Then 생성 201 및 목록 200을 반환하고 HttpOnly/Secure/SameSite=Lax 쿠키가 전달된다.
- Given 공개 주소에서 유효한 요청을 제출, When 같은 쿠키로 job을 조회, Then 제출 202 후 300초 이내 completed와 결과를 반환한다. 모델·검색 등 외부 의존성 실패는 연결 성공과 구분하여 기록한다.

Production 공개 주소 재연결 검증 결과 (2026-10-06 12:12 KST, Preview 미검증):
- 이전 alias deployment `dpl_CAcS4dWGQ2CgSqXkQynCbX3M78tg`의 소스를 재빌드하여 `dpl_wjcXPr6HnSSQir9TEyAukN2VU5Wx`를 배포했다. READY와 기존 공개 alias의 새 deployment ID 일치를 확인했다. alias 갱신·ID 확인은 같은 Vercel 절의 공통 공개 주소 갱신 절차를 따른다. 소스 교체 없이 주소 환경변수만 갱신했다.
- 공개 페이지 200, 생성된 배포와 정적 asset 11개 일치, 쿠키 없는 API JSON 401, 새 대화 생성 201, 대화 목록/이력 200, 쿠키 HttpOnly/Secure/SameSite=Lax/Path=/ 통과.
- 실제 공개 주소에서 `캐릭터를 정면에서 전신으로 그릴 레퍼런스를 찾아줘`를 제출하여 202 후 300초 이내 completed/success와 정면 Pin/썸네일 8개를 반환했다. job `e7cbafb7-856f-4d0d-9703-c5e724df42d9`, attempt=3. 이 검증은 연결 복구 smoke이며 전체 해석 품질 검증은 아니다.
- frontend 테스트 55 passed. MCP 무인증 접근 403 유지, API의 MCP_BASE_URL 및 MCP_ALLOWED_HOST 일치 확인. GCP 리소스/이미지 변경 및 GitHub commit/push/PR 없음.
- 복구가 필요하면 기존 deployment ID에 공개 alias를 다시 연결할 수 있다. 단, 이전 배포는 변경 전 backend 주소를 참조하므로 API 404가 다시 발생할 수 있다.

### Cloud Run

- 기존 API+SearXNG sidecar와 IAM 보호 MCP 구성을 유지한다. region은 기존 `asia-northeast3`로 통일한다.
- API 서비스는 공개 호출을 허용한다. Vercel rewrite가 Cloud Run IAM 토큰을 생성하지 않기 때문이다. 세션 소유권은 API가 검증한다. MCP는 인증 필수로 유지한다.
- API 서비스에 **instance-based billing / `--no-cpu-throttling`**, **service-level minimum instances 1 (`--min=1`)**, service-level maximum instances 1 (`--max=1`)을 적용한다. 기존 `--min-instances=0`, `--max-instances=3`과 충돌하는 revision 설정은 제거한다.
- API 컨테이너 초기 자원은 CPU 1, memory 512Mi, port 8000, request concurrency 80, timeout 300초를 유지한다. sidecar 기존 자원·startup probe를 유지한다.
- uvicorn process는 인스턴스당 1개, `WORKER_CONCURRENCY=5`를 명시한다. revision 전환 중 인스턴스가 잠시 겹칠 수 있으므로 최대값을 전역 job 동시성의 절대 보장으로 해석하지 않는다. 중복 claim과 stale write는 DB 계약으로 막는다.
- 인스턴스는 항상 종료·교체될 수 있다. 10초 heartbeat, 30초 lease, 최대 3 attempts 및 세션별 순차 처리 계약을 유지한다.
- worker가 실행되는 API 서비스 계정에 MCP `roles/run.invoker`와 필요한 Secret Manager secret의 접근 권한을 부여한다.
- 최소 인스턴스와 상시 CPU는 유휴 시간에도 과금된다. 실제 project 예산과 운영 기간을 배포 전 기록한다.

### backend 환경변수와 데이터

| 변수 | 값/저장 위치 |
| --- | --- |
| `ENVIRONMENT` | `production` |
| `DATABASE_URL` | 환경별 Neon branch, Secret Manager |
| `OPENROUTER_API_KEY` | Secret Manager |
| `LLM_MODEL` / `LLM_TIMEOUT_SECONDS` | `openai/gpt-4.1-mini` / `180` |
| `INTERPRETER_PROMPT_PATH` | `/app/prompts/uhkegryo-interpreter-v4.md` |
| `INTERPRETER_PROMPT_VERSION` | `uhkegryo-interpreter-v4` |
| `STRUCTURED_OUTPUT_SKILL_PATH` | `/app/skills/structured-output/SKILL.md` |
| `TERM_CARDS_PATH` | `/app/term-cards` |
| `WORKER_CONCURRENCY` | `5` |
| `MCP_ENABLED` / `MCP_BASE_URL` | `true` / 환경별 MCP HTTPS URL + `/mcp` |
| `SEARXNG_BASE_URL` | 기존 sidecar의 `http://localhost:8080` |
| `LANGFUSE_HOST` | 환경별 기존 공유 Langfuse HTTPS URL |
| `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` | 대상 Langfuse project의 Secret Manager secret |
| `SEARXNG_SECRET` | sidecar용 Secret Manager secret |

- 표의 환경별 주소·project·secret version은 실제 리소스 조회 후 배포 기록에 적는다. localhost는 컨테이너 내부 SearXNG 연결에만 허용한다.
- API 배포는 `--update-env-vars`로 관련 값을 갱신하고 기존 공유 Langfuse URL 등 무관한 환경변수를 보존한다. API만 상시 CPU·최소 인스턴스 설정을 적용하며 MCP의 요청 기반 실행은 유지한다.
- 기존 배포에 추가 비밀값이 있으면 이 작업에서 무관하게 제거하지 않는다. 환경변수 갱신 시 Langfuse target alias가 서로 충돌하지 않는지 확인한다.
- migration은 `backend.db.migrate.migrate`를 사용하는 기존 절차로 대상 DB에 1회 실행한다. API startup에서 자동 실행하지 않는다.
- Secret Manager version과 Docker image digest를 배포 기록에 고정한다. migration과 API/worker는 동일 대상 DB를 사용한다.
- DB 영속 구조, Pin 보관 경계와 trace 보안 규칙을 변경하지 않는다.

- Vercel 업로드에는 frontend가 import하는 docs/domains/illustration-reference/term-cards/*.json 6개를 포함한다. 문서 전체 제외 규칙은 이 빌드 입력을 제외하지 않아야 한다.

### 구현·배포 순서와 변경 범위

1. 로컬에서 `frontend`의 `npm ci`, `npm test`, `npm run build`와 기존 backend의 API·세션·worker·배포 관련 회귀 테스트를 실행한다.
2. 대상 리소스와 secret version, 예산, rollback 후보를 확인하고 Preview DB migration을 실행한다.
3. Cloud Run 설정에서 billing/min/max, worker 환경변수, MCP IAM을 적용하고 image digest·revision을 기록한다.
4. Vercel Preview를 만들고 AC를 실제 브라우저·DB·Cloud Run 설정 조회로 검증한다.
5. 운영 DB migration 및 동일 commit 배포 후 운영 smoke를 수행한다. 파괴적 migration이면 이 배포 범위에서 진행하지 않는다.
6. 기록에는 commit, image digest, revision, Vercel deployment URL, 비밀값 없는 설정 요약, AC 결과와 복구 절차를 포함한다.

- 후속 구현 변경은 `cloudbuild.yaml`의 관련 배포 설정, 필요한 배포 검사/테스트와 배포 기록으로 제한한다. Next.js 설정은 현재 계약을 충족하면 수정하지 않는다.
- PR당 코드 변경 400줄을 넘으면 구현을 독립 검토 가능한 범위로 분리한다. 사용자 승인 없이 GitHub commit/push/PR 또는 실제 배포를 수행하지 않는다.
- 공식 근거: [Cloud Run billing](https://docs.cloud.google.com/run/docs/configuring/billing-settings), [minimum instances](https://docs.cloud.google.com/run/docs/configuring/min-instances), [Vercel rewrites](https://vercel.com/docs/routing/rewrites), [Vercel environment variables](https://vercel.com/docs/environment-variables).

### 팀 운영 종료와 비용 분리

- 종료 전 비밀값 없는 소스·설정 예시·검증 기록과 시연 영상을 전달한다. 실제 사용자 대화·쿠키·DB dump·API key를 개인 데모 fixture로 복사하지 않는다.
- 각 개인 Vercel deployment가 개인 데모 또는 자기 backend를 사용하고 팀 API/MCP/DB/LLM/관측 서비스를 호출하지 않는지 확인한다. 자동 배포 trigger도 공용 서비스를 다시 생성하지 않도록 중지한다.
- 종료 대상 목록은 Cloud Run API/MCP, SearXNG, Langfuse VM·컨테이너·디스크·IP, Artifact Registry 이미지, Secret Manager, Cloud Build trigger, 유료 DB 및 외부 LLM 구독/충전 설정까지 실제 사용 리소스로 작성한다.
- 공용 데이터 보존·삭제와 유료 리소스 삭제는 소유자 승인 후 실행한다. 종료 날짜와 담당자, 남겨둔 리소스의 사유·예상 비용을 기록한다. 최소 인스턴스 0개만으로 완전한 비용 종료를 주장하지 않는다.
- 인계가 끝난 공용 key는 폐기하거나 회전하고 불필요한 IAM 권한을 회수한다. 개인 key는 인계하지 않는다.
- 승인된 전용 리소스 정리 후 Billing 보고서에서 사용일 기준 추가 사용량을 확인한다. 청구 반영 지연·이전 사용분은 별도로 구분한다. 예산 알림을 자동 지출 차단으로 취급하지 않는다.

## AC (Given-When-Then)

- **AC-16 · 기존 공개 주소** — Given 기존 공개 주소 `https://uhkegryo.vercel.app/`와 기존 프로젝트에 생성한 `READY` deployment, When 배포 갱신과 alias 연결을 수행, Then 공개 주소 조회의 deployment ID가 새 ID와 일치하고 페이지 HTTP 200·최신 빌드 asset 일치·same-origin API 정상 응답을 확인하며 완료 보고에 기존 공개 주소를 사용한다.

- **AC-15 · 과금 배포 차단** — Given 운영 승인이 false 또는 시작일·종료일·예산·비용 부담자·결제 계정·종료 담당자·종료 절차 중 하나가 빈 값, When Cloud Build 시작, Then 이미지 빌드와 배포 전에 실패한다. 모든 값과 명시적 승인이 있을 때만 상시 worker 배포를 허용한다.

- **AC-01 · 빌드** — Given Node.js 22.x와 lockfile, When frontend install/test/build 및 관련 backend 회귀 테스트를 실행, Then 모두 통과하고 배포 대상 commit을 기록한다.
- **AC-02 · 배포 설정** — Given Cloud Run API revision, When service/revision 설정을 조회, Then instance-based billing, service min/max=1, 단일 uvicorn process, WORKER_CONCURRENCY=5 및 충돌 없는 scaling 설정을 확인한다.
- **AC-03 · 실제 결과** — Given 정상 외부 의존성과 별도 세션 3개, When Preview에서 유효 입력을 제출, Then 각 요청은 202와 job_id를 반환하고 300초 이내 completed 결과와 용어·Pin 결과 또는 기존 부분 결과 안내를 표시한다.
- **AC-04 · 요청 없는 worker** — Given 요청 제출 직후 polling을 중단한 queued job, When API health를 포함한 HTTP 요청 없이 300초 동안 DB에서 상태만 관찰, Then job이 completed에 도달하고 worker 진행 증거를 남긴다.
- **AC-05 · 쿠키와 대화** — Given Preview에서 생성한 대화, When 쿠키 속성을 확인하고 새로고침 후 대화를 조회, Then HttpOnly/Secure/SameSite=Lax/Path=/과 기존 만료 계약을 만족하고 동일 대화 이력을 표시한다.
- **AC-06 · 소유권** — Given 세션 A의 job과 독립 세션 B, When B가 A의 job을 조회, Then 기존 API 계약의 접근 거부 응답을 반환하고 A의 결과를 노출하지 않는다.
- **AC-07 · 중단 복구** — Given attempt<3인 실행 중 job, When Preview worker 인스턴스를 재시작하여 heartbeat가 중단, Then lease 만료 후 attempt가 증가하여 재실행되고 stale attempt는 결과를 덮어쓰지 못한다. 기존 worker 회귀 테스트와 Preview 재시작 기록으로 검증한다.
- **AC-08 · IAM과 실패** — Given 배포 MCP, When 무인증 및 API 서비스 계정으로 도구 호출, Then 무인증은 거부되고 서비스 계정은 성공한다. 외부 장애 회귀 테스트는 기존 failure/partial result 계약을 통과한다.
- **AC-09 · 환경 분리** — Given Preview/Production 설정, When secret 참조·DB branch·API origin을 비교, Then Preview는 운영 DB에 쓰지 않으며 브라우저 bundle에 backend 비밀값이 포함되지 않는다.
- **AC-10 · 복구** — Given 이전 호환 revision/deployment, When Preview에서 rollback 절차를 실행, Then UI→API→worker 결과 흐름이 복구되고 DB 자동 역migration 없이 기존 대화를 조회한다.
- **AC-11 · 운영 승인** — Given AC-01~10의 통과 기록, When 승인된 Production을 배포, Then 실제 운영 입력 1건과 대화 재조회가 성공한다. 외부 검증 미실행/실패 항목은 미검증/실패로 기록하고 배포 완료로 보고하지 않는다.
- **AC-12 · 운영 기간** — Given 팀 배포 준비, When 배포 기록을 검토, Then 시작일·종료일·비용 부담자·결제 계정·예산·종료 담당자가 모두 명시된다.
- **AC-13 · 종료 인계** — Given 개인 배포가 준비된 팀 종료 시점, When 개인별 주요 사용자 흐름과 네트워크를 검사, Then 팀 backend·DB·MCP·LLM·관측 서비스 호출이 0건이고 실제 사용자 데이터와 공용 secret이 개인 배포에 포함되지 않는다.
- **AC-14 · 비용 종료** — Given 소유자가 승인한 전용 리소스 종료 목록, When 정리와 trigger 중지를 수행, Then 종료 증거와 잔존 리소스·비용 담당자를 기록하고 Billing 반영 후 종료 이후 사용량을 확인한다. 미확인 비용은 0원으로 보고하지 않는다.

운영 승인 gate: cloudbuild.yaml 첫 단계는 scripts/check-team-operation.py를 실행한다. _TEAM_OPERATION_APPROVED 기본 false, _TEAM_OPERATION_START/_END/_BUDGET/_BILLING_OWNER/_BILLING_ACCOUNT/_SHUTDOWN_OWNER/_SHUTDOWN_PROCEDURE 기본 빈 값이다. Cloud Build trigger substitutions에 비밀값 없이 승인 기록을 지정한다. false/공백은 배포 차단, true와 모든 기록은 허용한다. 이 gate는 기존 리소스를 종료하거나 예산을 자동 차단하지 않는다. 종료 담당자는 지정한 종료일에 Cloud Run/API/MCP 및 별도 Langfuse 리소스 종료·Billing 확인 절차를 수행한다.

배포 재현성: API deploy-api의 단일 기준 환경변수는 LLM_MAX_TOKENS=2048을 명시한다. Given 새 API 배포, When revision 환경변수 확인, Then LLM_MAX_TOKENS는 2048이어야 한다. 배포 후 확인 명령: gcloud run services describe api-preview --project=proj2-509406 --region=asia-northeast3 --format=json. spec.template.spec.containers에서 API 컨테이너의 env를 확인하고 해당 항목이 없거나 값이 다르면 배포 검증 실패로 기록한다. 운영 승인이 없어 이번 보완에서 재배포하지 않는다.
