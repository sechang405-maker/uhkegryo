# 팀 Preview 배포 준비 기록 — 2026-10-04

## 대상과 상태

- 기준: `specs/vercel-deployment.md`.
- 현재 작업 트리의 기존 변경사항을 유지하고 배포 관련 설정만 추가했다. commit/push/PR은 수행하지 않았다.
- 실제 Preview API/MCP 서비스·Neon branch·GCP 결제 계정·Vercel 프로젝트는 미확정이다. 기존 문서의 GCP project는 `proj2-509406`, region은 `asia-northeast3`이나 이것을 Preview 대상으로 승인/검증한 것은 아니다.
- 운영 종료일·비용 예산·담당자: 미확정. 공용 또는 운영 DB migration을 임의 실행하지 않았다.

## 준비한 변경

- `cloudbuild.yaml`: API service min/max=1, revision min/max 기본값 복원, CPU throttling 해제.
- API worker에 MCP 활성화·동시성 5·카탈로그/structured-output 경로 명시.
- API 환경변수 갱신은 `--update-env-vars`로 기존 Langfuse 연결 설정을 보존한다.
- MCP 인증 필수 및 기존 실행 설정 유지. API 내부 worker 실행 구조 유지.
- `backend/tests/test_team_deployment.py`: 요청 없는 worker 설정과 기존 관측 target 보존 검사.

## 로컬 검증

| 검사 | 결과 |
| --- | --- |
| frontend `npm test` | 45 passed |
| frontend `npm run build` | 통과, Next.js 16.3.7 |
| 배포·MCP 설정, worker, API, cookie 회귀 테스트 | 59 passed |
| `git diff --check` | 통과 |
| Node.js 22.x 재현 | 미검증. 현재 호스트는 24.18.0 |
| backend 런타임 | Python 3.11.9에서 검증. Docker 목표 Python 3.12는 미검증 |
| Docker image build | 미실행. Docker 엔진 연결 실패 |

- backend 테스트 종료 시 Langfuse exporter timeout 메시지가 발생했다. 회귀 테스트 통과를 실제 Langfuse trace 수신 검증으로 해석하지 않는다.
- Python 의존성 설치 중 기존 전역 OpenTelemetry gRPC exporter 1.44.0과 새 OTLP 구성 1.45.0의 충돌 경고가 발생했다. Docker 환경 검증을 대체하지 않으며 추가 공유 환경 변경은 수행하지 않는다.

## 원격 작업 차단 요인과 다음 순서

1. Vercel CLI `whoami`는 `The specified token is not valid`로 실패했다. 사용자 로그인 후 프로젝트 연결·Preview 환경변수 설정·배포를 진행해야 한다.
2. 이 PC에서 gcloud 설치/인증 설정을 찾지 못했다. 인증된 GCP 실행 환경이 필요하다.
3. Preview 전용 Neon DB 및 API/MCP 리소스를 확인한 뒤 Secret Manager version·IAM·Langfuse target을 검증한다.
4. Preview 대상 DB에 migration을 실행하고 image digest를 고정하여 backend를 배포한다.
5. Vercel의 Preview 환경에 `/api`, demo=0, Preview API origin을 설정한 뒤 Preview를 배포한다.
6. 쿠키·소유권·실제 입력 3건·HTTP 요청 없는 worker 처리·재시작 복구·rollback AC 증거를 기록한다.

Preview URL, remote revision/image digest, 실제 E2E 결과는 아직 없다. 이 문서는 배포 준비 기록이며 배포 완료 보고가 아니다.

## 콘솔 확인 및 리소스 준비 (후속 확인)

- Vercel CLI 인증 완료: `surf7978-4706`, scope `yoon-tae-hyun`.
- Vercel 프로젝트 `uhkegryo-team-preview` 생성·로컬 연결 완료. Root Directory `frontend`, framework Next.js, Node.js 22.x, install `npm ci`, build `npm run build` 설정.
- Preview 환경변수 `NEXT_PUBLIC_API_BASE_URL=/api`, `NEXT_PUBLIC_UI_DEMO=0` 등록. API origin은 backend 배포 후 등록한다.
- GCP `proj2-509406` 콘솔 및 인증된 Cloud Shell 접근 확인. 기존 서비스는 IAM 보호 `mcp` 1개이며 API 서비스는 없다. 기존 MCP는 과거 이미지 `api:mcp-host-a1`을 사용한다.
- GCP Secret Manager에는 `DATABASE_URL`만 존재한다. 사용자는 로컬 OpenRouter/Langfuse/SearXNG key를 Preview 전용 secret으로 사용하는 것을 승인했다. 아직 전송하지 않았다.
- 제공된 Neon branch는 project `dev`의 기본 `production` branch다. 사용자 데이터를 복사하지 않는 schema-only branch `preview/team-vercel`을 생성했다.
- Preview branch ID: `br-blue-lab-b4tpwu5w`, 만료: 2026-10-11 12:42 KST. 이 날짜는 DB branch 자동 만료이며 GCP 리소스 자동 종료를 의미하지 않는다.
- 현재 작업 트리에서 환경파일·테스트·캐시를 제외한 backend 배포 archive 62개 파일을 로컬 임시 디렉터리에 준비했다. 별도 승인된 key 파일도 임시 준비했으며 원문을 출력하지 않았다.
- Cloud Shell 업로드 시 ChatGPT Chrome 확장의 파일 URL 접근이 꺼져 있어 차단됐다. 사용자에게 해당 설정 활성화를 요청했다. 실제 upload, migration, image build, Cloud Run API 배포 및 Vercel Preview deployment는 미실행이다.

## 인증·업로드 이후 진행

- 사용자가 Chrome 파일 URL 접근을 허용해 source archive와 승인한 secret 파일 업로드를 완료했다.
- Cloud Build 시도는 기본 compute 서비스 계정의 `storage.objects.get` 부족으로 실패했다. 권한 확대 대신 인증된 Cloud Shell의 Docker에서 직접 빌드했다.
- 원본 Dockerfile의 backend 이미지 빌드·push 완료. digest: `sha256:33a9ee420f335655b9e516fbdafadacd5685b209cd1c6b747b904d1be926c0bb`. 별도 미러 빌드도 수행했으나 배포에는 원본 이미지를 사용한다.
- Python 3.12 이미지에서 실제 카탈로그 로드와 v4 프롬프트·structured-output 파일 존재 검증 통과.
- schema-only branch의 복제된 테이블에 빈 migration ledger가 남아 초기 migration이 충돌했다. 기존 테이블/데이터를 삭제하거나 ledger를 임의 변경하지 않고, Preview branch 내 별도 빈 DB `preview_app`에 표준 migration을 적용했다. migration 4개 확인.
- `PREVIEW_DATABASE_URL` version 2는 `preview_app`을 가리키며 asyncpg에 맞게 `channel_binding` query를 제외하고 `sslmode=require`를 유지한다.
- `PREVIEW_OPENROUTER_API_KEY`, `PREVIEW_LANGFUSE_PUBLIC_KEY`, `PREVIEW_LANGFUSE_SECRET_KEY`, `PREVIEW_SEARXNG_SECRET` version 1 생성.
- 사용자 승인을 받아 `mcp-runtime`에 해당 Preview secret의 읽기 권한을 부여했다. Preview API 공개 접근도 승인받았다.
- Vercel dry run에서 기본 업로드 목록의 환경파일 포함을 확인해 실제 업로드 전에 `.vercelignore`를 추가했다. 재검증 결과 파일 61개, 환경파일 0개. 비밀값이 Vercel에 업로드된 것은 아니다.
- frontend `npm ci` 완료, 0 vulnerabilities. install 이후 테스트 45개와 production build 재검증 통과.
- SearXNG 이미지 build 완료 후 등록과 별도 `mcp-preview`·`api-preview` 배포를 시작했다. remote 완료 결과와 Preview URL은 다음 검증에서 기록한다.

## 2026-10-04 실제 Preview 배포·검증 결과

- 운영 시작: 2026-10-04. 팀 종료 예정일과 예산: 사용자 답변 **미정**. 비용은 `proj2-509406`에 연결된 사용자 GCP 결제 계정에 귀속된다. 결제 계정 ID와 종료 담당자는 별도 확인이 필요하다. 자동 Cloud Run 종료는 설정하지 않았다.
- source 기준 HEAD: `a0c49f761745dfc197513b16011257ee9367e640` 및 현재 미커밋 작업 트리. 기존 사용자 변경을 포함한 실제 archive를 배포했으며 GitHub commit/push는 수행하지 않았다.
- API: `https://api-preview-fgdrdxsn6q-du.a.run.app`, revision `api-preview-00001-4m5`, Ready=True. `/health` 200.
- MCP: `https://mcp-preview-fgdrdxsn6q-du.a.run.app/mcp`, revision `mcp-preview-00002-d7k`. 무인증 403. Preview runtime 서비스 계정에 전용 invoker 권한 부여.
- API service min/max=1/1, revision `cpu-throttling=false`, 단일 uvicorn 프로세스와 worker concurrency=5를 확인했다. API와 SearXNG sidecar 각각 CPU 1, memory 512Mi. API는 유휴 시간에도 과금된다.
- backend digest: `sha256:33a9ee420f335655b9e516fbdafadacd5685b209cd1c6b747b904d1be926c0bb`. DB secret version 2, OpenRouter/Langfuse/SearXNG secret version 1 고정.
- Vercel 원격 빌드에서 카탈로그 JSON 누락을 확인해 `.vercelignore`를 수정했다. 최종 dry run: 68 files, 환경파일 0, 카탈로그 JSON 6. frontend 밖의 카탈로그는 기존 Next.js root 설정을 유지해 포함한다.
- 새 Vercel 프로젝트의 최초 CLI 배포는 `--target=preview`도 Production으로 분류됐다. 최초 실패 배포 2개는 제거했다. 후속 배포는 실제 target=preview로 확인했다.
- 최종 Preview 시도: `dpl_H1AMaZsGtYntJFx2cnoPeEJ5hJ22`, URL `https://uhkegryo-team-preview-lrxhzhbu4-yoon-tae-hyun.vercel.app`. **서비스 가능한 URL이 아니다.** Vercel 화면의 Blocked: commit 작성자 `sechang405-maker`가 프로젝트 기여 권한을 갖고 있지 않으며 Hobby는 private repository 협업을 지원하지 않는다는 안내. 사용자에게 계정 연결/협업 플랜 해결을 요청했다. 작성자 위장, 저장소 공개 전환 또는 유료 업그레이드를 수행하지 않았다.

### 실제 API 검증

- 최초 세션 3건: 모두 202. 포즈+정면+전신 및 달리기+측면+전신 입력은 3회 시도 후 `LLM_INVALID_STRUCTURED_OUTPUT`. 앉기+위에서 보는 입력은 completed/partial_result, `PIN_SEARCH_UNAVAILABLE`.
- 전신 입력을 로컬에서 재현: LLM selection/context update가 `view_full_body`에 role=layout을 붙여 카탈로그 role=view와 불일치. resolver가 거절했다. 카탈로그 검증을 완화하거나 제품 계약을 변경하지 않았다.
- 기본 입력: 정면, 뒷모습, 앉기+위에서 보기의 별도 세션 3건은 모두 202 → completed/partial_result. API polling 없이 PostgreSQL 상태만 관찰하여 완료했다. 다만 전부 `PIN_SEARCH_UNAVAILABLE`이므로 정상 Pin 검색 성공으로 보고하지 않는다.
- 기본 입력 job IDs: `4e0c66a7-f339-4fab-bc01-7bbd458ae3f2`, `56c5c654-b936-4986-b515-34c4dfca0902`, `efb087fe-6713-4ed7-9609-966761bf4582`.
- 제출 응답 쿠키 HttpOnly/Secure/SameSite=Lax/Path=/ 확인. 소유 세션 조회 200, 동일 idempotency key 재전송 202 및 같은 job_id, 다른 유효 세션의 조회 404/job_not_found 확인.
- 이 API 검증은 Vercel 프록시와 실제 브라우저 새로고침 검증을 대체하지 않는다.

### AC 현황과 남은 작업

- 로컬 frontend 45 / backend 관련 59 테스트 통과, Python 3.12 배포 이미지 카탈로그 로드 통과, 원격 CPU/scaling 설정 검증 통과.
- 기본 API 입력·요청 없는 worker 처리·소유권 검증 통과. 복합 입력 2건 실패와 Pin 검색 장애가 남아 있다.
- Vercel 브라우저 E2E, 쿠키 프록시 전달/대화 새로고침, 실제 worker 재시작 복구, rollback, Langfuse trace 수신은 미검증. 현재 Preview 첫 API revision이므로 이전 정상 API revision은 없다.
- Production 배포와 개인 무료 데모 구현·팀 종료 리소스 정리는 이번 Preview 작업에서 실행하지 않았다.
- 운영 종료일이 미정이어도 Neon Preview branch는 **2026-10-11 12:42 KST** 자동 만료된다. Cloud Run은 DB 만료 후에도 자동 종료되지 않으며 비용이 계속 발생할 수 있다.
- 배포 완료 상태가 아니다. Vercel 접근 차단 해결 뒤 업로드 입력으로 다시 Preview 배포하고, 실패·미검증 항목을 해결/검증해야 한다.

### MCP 인증 후속 검증과 임시 파일 정리

- 인증된 Cloud Shell 사용자 identity token으로 MCP SDK의 초기화·도구 목록 조회·실제 카드/검색 도구 호출 성공. 도구 목록: `get_active_term_card`, `search_pinterest_pins`.
- 카드 도구의 실제 TextContent JSON은 `status=found`, `term_id=view_front`. 검색 도구의 실제 TextContent JSON은 `role=view`, `pins=[]`, `code=PIN_SEARCH_UNAVAILABLE`. 따라서 도구 연결 자체와 검색 공급자 장애는 구분한다. 이 검증의 identity는 Cloud Shell 사용자이며 API runtime 서비스 계정의 별도 직접 도구 검증을 대체하지 않는다.
- 기본 세션 간 소유권 검사 최종 404/job_not_found 확인.
- 승인된 key를 전달하기 위해 만든 로컬/Cloud Shell 임시 JSON 복사본을 제거했다. 원본 사용자 `.env`와 Secret Manager version은 유지했다.
- Vercel 차단 화면을 캡처해 작업 artifact 디렉터리에 보관했다. `.vercelignore` 최종 업로드 검증과 `git diff --check` 통과.

## 발표·시연 기간에 맞춘 DB 만료 연장

- 사용자 요청: 2026-10-12 발표·시연, 10월 13일까지 Preview DB 유지.
- Neon branch br-blue-lab-b4tpwu5w 만료를 2026-10-14 00:00:00 Asia/Seoul로 변경하고 저장 후 Expires 표시를 확인했다. 위 기록의 10월 11일 만료 예정일을 대체한다.
- 기존 preview_app DB, 연결 주소와 데이터는 유지한다. Cloud Run 종료 예정일 및 예산은 여전히 미정이며 자동 종료는 설정하지 않았다.

## 2026-10-05 再리뷰 보완
최신 #110을 병합해 cloudbuild.yaml 충돌을 해결하고 기존 API 환경변수 보존·Compose prompt pair 검증을 유지했다. 현재 운영 기록은 미확정이므로 저장소 기본 배포는 check-team-operation 단계에서 차단한다. 비용 부담자가 승인하고 trigger substitutions에 시작/종료일·예산·담당자·결제 계정·종료 절차를 기록하기 전 상시 worker 설정은 새 배포에 적용되지 않는다. 이미 배포된 리소스에는 영향이 없으며 자동 종료나 무료 운영을 주장하지 않는다.
