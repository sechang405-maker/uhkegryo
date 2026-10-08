# 배포 가이드: GCP Cloud Run + Vercel (무료 티어)

## 아키텍처 개요 (무료 티어)

```
┌─────────────┐     HTTPS      ┌──────────────────┐
│   Vercel    │ ─────────────► │  Cloud Run (api) │  --min-instances=0 (유휴 시 $0)
│  (Frontend) │   REST API     │  FastAPI (공개)  │  --max-instances=3
                               │  + SearXNG sidecar│  (내부 localhost)
└─────────────┘                └────────┬─────────┘
                                        │
                                        │ Internal (OIDC 토큰)
                                        ▼
                               ┌──────────────────┐
                               │ Cloud Run (mcp)  │  --no-allow-unauthenticated
                               │  MCP (내부 전용)  │  --min-instances=0
                               └────────┬─────────┘
                                        │
                                        ▼
                               ┌──────────────────┐
                               │  Neon PostgreSQL │  -- Free Tier: 0.5GB storage
                               │  (Free Tier)     │  -- Auto-suspend 5min 유휴
                               └──────────────────┘
```

- **공개 API**: Cloud Run 서비스 `api` (FastAPI, `/health`, `/api/*`) — `--allow-unauthenticated`
- **내부 MCP**: Cloud Run 서비스 `mcp` (FastMCP, `/mcp`) — `--no-allow-unauthenticated`, IAM 보호
- **프론트엔드**: 별도 레포 `proj2-frontend` → Vercel 연동 (Hobby 플랜 무료)
- **DB**: **Neon 무료 PostgreSQL** (Cloud SQL 대신 — 월 $0)
- **시크릿**: Secret Manager
- **CI/CD**: Cloud Build (GitHub push → 빌드 → 배포)
- **MCP 인증**: Cloud Run IAM (서비스 간 호출만 허용, 브라우저 직접 접근 차단)
- **이미지**: API와 MCP는 앱 이미지를 공유하고, API 서비스는 SearXNG sidecar 컨테이너도 함께 실행합니다.
- **예상 월 비용**: **$0** (무료 할당량 내, 초과 시 과금 가능)

---

---

## 1. 사전 준비

```bash
# GCP 프로젝트 설정 (기존 프로젝트 사용)
gcloud config set project proj2-509406
gcloud auth login
gcloud auth application-default login

# 필요 API 활성화 (Cloud SQL, VPC Access 불필요)
gcloud services enable run.googleapis.com artifactregistry.googleapis.com secretmanager.googleapis.com cloudbuild.googleapis.com
```

---

## 2. Neon 무료 PostgreSQL 생성 (필수)

1. **Neon 가입**: https://neon.tech → GitHub/GitHub으로 로그인
2. **프로젝트 생성**: 프로젝트명 `proj2-4`, 리전 `Asia Pacific (Seoul)` 권장
3. **연결 문자열 복사**: Dashboard → Connection Details → `psql` 탭
   - 형식: `postgresql://user:password@ep-xxx.ap-northeast-1.aws.neon.tech/dbname?sslmode=require`
4. `postgresql://` 형식 그대로 **Secret Manager `DATABASE_URL`에 저장** (`asyncpg`에 맞춰 `+asyncpg`를 붙이지 않는다.)

> Neon 무료 티어: 0.5GB 스토리지, 5분 유휴 시 자동 일시정지(비용 0), 브랜칭 기능 포함

---

## 3. 인프라 생성 (한 번만 실행)

```bash
# 무료 티어 설정 스크립트 실행
bash scripts/gcp-setup-free.sh
```

스크립트가 생성하는 리소스:
- Artifact Registry: `asia-northeast3-docker.pkg.dev/proj2-509406/docker-repo`
- **Cloud SQL 없음, VPC 커넥터 없음** (비용 절감)
- Secret Manager: 6개 시크릿 생성 안내 (직접 값 입력 필요)

**수동 입력 필요 시크릿 6개** (Secret Manager 콘솔 또는 CLI):
1. `OPENROUTER_API_KEY` — OpenRouter 키
2. `LANGFUSE_PUBLIC_KEY` — Langfuse 공개 키
3. `LANGFUSE_SECRET_KEY` — Langfuse 비밀 키
4. `SESSION_SECRET` — 임의 32자 문자열 (`openssl rand -base64 32 | tr -d "=+/" | cut -c1-32`)
5. `DATABASE_URL` — **Neon 연결 문자열** (`postgresql://...`)
6. `SEARXNG_SECRET` — SearXNG 설정용 임의의 긴 비밀값

**프롬프트 파일 환경변수** (API 서비스 전용, MCP 서비스 불필요):
- `INTERPRETER_PROMPT_PATH=/app/prompts/uhkegryo-interpreter-v4.md`
  - Docker 이미지 내부 경로와 반드시 일치해야 합니다.
  - 설정 누락, 파일 부재·읽기 실패, 필수 섹션 또는 닫힌 code fence 누락 시 adapter 초기화에서 `PromptConfigurationError` (`CONFIGURATION_ERROR`, 재시도 불가)로 실패합니다.

- `INTERPRETER_PROMPT_VERSION=uhkegryo-interpreter-v4`: 경로와 함께 설정합니다. 설정 파일 변경은 실제 Cloud Run 배포 완료를 뜻하지 않습니다.

**OpenRouter 모델·timeout 환경변수** (API 서비스 전용):
- `OPENROUTER_API_KEY`: Secret Manager에서 제공하는 OpenRouter API key
- `OPENROUTER_BASE_URL=https://openrouter.ai/api/v1`
- `LLM_MODEL=openai/gpt-4.1-mini`: 모델 교체는 이 값만 변경합니다. `OPENROUTER_MODEL`은 사용하지 않습니다.
- `LLM_TIMEOUT_SECONDS=180`: 기본 호출 timeout은 180초이며 SDK 내부 재시도는 비활성화됩니다.
- `cloudbuild.yaml`의 API 배포 환경변수도 같은 모델과 timeout을 지정합니다. MCP 서비스에는 이 설정을 추가하지 않습니다.

CLI로 한 번에 입력 예시:
```bash
gcloud secrets create OPENROUTER_API_KEY --data-file=- --project=proj2-509406 <<< 'sk-or-xxx'
gcloud secrets create LANGFUSE_PUBLIC_KEY --data-file=- --project=proj2-509406 <<< 'pk-lf-xxx'
gcloud secrets create LANGFUSE_SECRET_KEY --data-file=- --project=proj2-509406 <<< 'sk-lf-xxx'
gcloud secrets create SESSION_SECRET --data-file=- --project=proj2-509406 <<< 'your-32-char-secret'
gcloud secrets create DATABASE_URL --data-file=- --project=proj2-509406 <<< 'postgresql://user:pwd@ep-xxx.neon.tech/db?sslmode=require'
gcloud secrets create SEARXNG_SECRET --data-file=- --project=proj2-509406 <<< 'replace-with-a-long-random-value'
```

---

## 4. Cloud Build 트리거 생성

1. Cloud Build 콘솔 → **트리거** → **저장소 연결**
2. GitHub `aihuman-7th/proj2-4` 선택
3. 트리거 설정:
   - **이름**: `deploy-api`
   - **이벤트**: 브랜치 푸시
   - **브랜치 정규식**: `^main$`
   - **포함된 파일 필터**: `backend/**`, `searxng/**`, `Dockerfile`, `cloudbuild.yaml`, `.env.example`
   - **빌드 구성**: `cloudbuild.yaml` (레포 루트)
4. **만들기** 클릭

이제 `main` 브랜치에 `backend/`, `searxng/`, `Dockerfile`, `cloudbuild.yaml`, `.env.example` 변경사항을 푸시하면 자동 빌드·배포 실행.

---

## 4-1. Cloud Build 트리거 상세 설정

`cloudbuild.yaml`의 substitutions와 트리거 포함 경로:

| 설정 항목 | 값 |
|---|---|
| **브랜치** | `^main$` |
| **포함된 파일 필터** | `backend/**`, `searxng/**`, `Dockerfile`, `cloudbuild.yaml`, `.env.example` |
| **빌드 구성** | `cloudbuild.yaml` (레포 루트) |
| **Substitutions** | `_REGION=asia-northeast3`, `_ARTIFACT_REGISTRY=asia-northeast3-docker.pkg.dev`, `_ARTIFACT_REPO=docker-repo`, `_API_SERVICE_NAME=api`, `_MCP_SERVICE_NAME=mcp`, `_MCP_CALLER_SA=mcp-caller` |

> **참고**: 실제 트리거는 Cloud Build 콘솔에서 생성·관리됩니다. 위 설정은 `cloudbuild.yaml` 주석과 이 문서에 기록해 둡니다.

---

## 4-2. MCP 인증 (Cloud Run IAM)

MCP 서비스(`mcp`, `/mcp`)는 **Cloud Run IAM**으로 보호됩니다.

### 인증 방식
- **허용**: Cloud Run 서비스 간 호출 (공개 API 서비스 `api` → MCP 서비스 `mcp`, 동일 프로젝트 내)
- **차단**: 일반 브라우저의 `/mcp` 직접 호출, 인증되지 않은 외부 요청
- **호출자**: `mcp-caller` 서비스 계정 (`roles/run.invoker` 권한 보유)

### 설정 방법 (Cloud Build에서 자동 수행)
1. **공개 API 서비스 `api`**: `--allow-unauthenticated`로 배포 (`/health`, `/api/*` 공개)
2. **MCP 서비스 `mcp`**: `--no-allow-unauthenticated`로 배포 (인증 필수)
3. **IAM 바인딩**: `mcp-caller@<project>.iam.gserviceaccount.com`에 `roles/run.invoker` 부여 (Cloud Build 단계 4에서 자동)
4. **메인 API에서 MCP 호출 시**: `Authorization: Bearer <OIDC 토큰>` 헤더 포함 (Google Cloud 클라이언트 라이브러리가 자동 처리)

### 로컬 개발·테스트 시 주의사항
- **로컬에서는 IAM 검증 불가** → 단일 컨테이너로 실행 (`MCP_ENABLED=true` 시 MCP 마운트)
- `docker compose up` 시 공개 API와 MCP가 동일 포트(8000)에서 서비스됨
- 로컬에서는 인증 없이 접근 가능 (개발 편의)
- 배포 시에는 반드시 두 서비스 분리 + IAM 정책 적용 확인

### 기존 JWT 인증 제거
- `backend/shared/auth.py`에서 MCP용 JWT(`verify_token`, `create_token`) 제거 완료
- 메인 API 세션 인증은 쿠키 기반(`get_session_id`, `get_current_user`)만 유지

---

## 4-3. 서비스 계정 생성 (최초 1회)

```bash
# MCP 호출용 서비스 계정 생성
gcloud iam service-accounts create mcp-caller --project=proj2-509406

# Cloud Build가 배포 시 자동으로 IAM 바인딩 수행 (cloudbuild.yaml의 bind-mcp-invoker 단계)
# 수동 실행 필요 시:
gcloud run services add-iam-policy-binding mcp \
  --region=asia-northeast3 \
  --member="serviceAccount:mcp-caller@proj2-509406.iam.gserviceaccount.com" \
  --role="roles/run.invoker" \
  --project=proj2-509406
```

## 5. 로컬 개발

```bash
# .env 파일 생성 (예시)
cp .env.example .env
# .env 편집: OPENROUTER_API_KEY, LLM_MODEL, LLM_TIMEOUT_SECONDS, LANGFUSE_* 등 입력
# DATABASE_URL에는 Neon dev 브랜치 연결 문자열 필수 입력
# TERM_CARDS_PATH 미설정 시 자동 탐지 (레포 내 term-cards 디렉터리)
# INTERPRETER_PROMPT_PATH=./prompts/uhkegryo-interpreter-v4.md (필수; 폴백 없음)

# 전체 스택 실행 (Neon dev 브랜치 사용)
docker compose up --build

# API 확인
curl http://localhost:8000/health
# MCP는 로컬에서 동일 컨테이너에 마운트됨 (MCP_ENABLED=true 시)
MCP_ENABLED=true docker compose up --build
curl http://localhost:8000/mcp/health
```

- FastAPI (공개 API): `http://localhost:8000` — `/health`, `/api/*`
- MCP 엔드포인트: `http://localhost:8000/mcp` (Streamable HTTP, `MCP_ENABLED=true` 시에만 마운트)
- 로컬 DB: **Neon dev 브랜치** 사용 (운영과 동일 환경, 브랜칭 기능 활용)
- `.env` 파일이 없거나 `DATABASE_URL`이 설정되지 않으면 컨테이너 시작 실패
- TERM_CARD 경로: `TERM_CARDS_PATH` 미설정 시 레포 내 `docs/domains/illustration-reference/term-cards/` 자동 탐지

> **참고**: 로컬에서는 단일 컨테이너로 공개 API + MCP 동시 실행. 프로덕션은 별도 Cloud Run 서비스(`api`, `mcp`)로 분리 배포.

---

## 6. 프론트엔드 배포 (Vercel 무료)

### 별도 레포 생성 권장
```bash
gh repo create proj2-frontend --public --clone
cd proj2-frontend
npx create-next-app@latest . --typescript --tailwind --eslint --app --src-dir --import-alias "@/*"
```

### Vercel 연결 (가이드)
1. Vercel 대시보드 → **Add New Project** → GitHub `proj2-frontend` 선택
2. 환경변수 추가:
   - `NEXT_PUBLIC_API_URL` = `https://api-xxx-asia-northeast3.run.app` (Cloud Run URL)
3. 배포 완료 → `https://proj2-frontend.vercel.app` 생성됨 (Hobby 플랜 무료)

> **참고**: 이 문서는 연동 가이드입니다. 실제 프론트엔드 레포(`proj2-frontend`) 생성 및 배포는 별도 진행 필요.

### CORS 허용 (Cloud Run 측)
```bash
gcloud run services update api \
  --region=asia-northeast3 \
  --update-env-vars=ALLOWED_ORIGINS=https://proj2-frontend.vercel.app \
  --project=proj2-509406
```
또는 `cloudbuild.yaml`의 `--set-env-vars`에 추가 후 재배포.

---

## 7. 커스텀 도메인 (선택)

| 서비스 | 명령어 |
|---|---|
| Cloud Run (공개 API) | `gcloud run domain-mappings create --service=api --domain=api.myapp.com --region=asia-northeast3` |
| Cloud Run (MCP) | `gcloud run domain-mappings create --service=mcp --domain=mcp.myapp.com --region=asia-northeast3` |
| Vercel | 대시보드 → Project → Settings → Domains → Add |

> **참고**: MCP 서비스는 내부 전용이므로 커스텀 도메인 불필요. 필요 시에만 설정.

---

## 8. 주요 명령어 치트시트

```bash
# Cloud Run 로그 확인 (공개 API)
gcloud run services logs read api --region=asia-northeast3 --limit=50

# Cloud Run 로그 확인 (MCP)
gcloud run services logs read mcp --region=asia-northeast3 --limit=50

# Cloud Run 서비스 업데이트 - 공개 API (환경변수만 변경 시)
gcloud run services update api --region=asia-northeast3 --update-env-vars=KEY=VALUE --project=proj2-509406

# Cloud Run 서비스 업데이트 - MCP (환경변수만 변경 시)
gcloud run services update mcp --region=asia-northeast3 --update-env-vars=KEY=VALUE --project=proj2-509406

# Secret Manager 시크릿 업데이트
echo -n "new-value" | gcloud secrets versions add SECRET_NAME --data-file=- --project=proj2-509406

# Neon 콘솔에서 DB 상태 확인: https://console.neon.tech

# MCP 서비스 IAM 바인딩 확인
gcloud run services get-iam-policy mcp --region=asia-northeast3 --project=proj2-509406
```

---

## 9. 트러블슈팅

| 증상 | 원인 | 해결 |
|---|---|---|
| 배포 후 500 에러 | 시크릿 누락 | Secret Manager에 6개 시크릿 모두 버전 확인 |
| DB 연결 실패 | Neon 일시정지 | Neon 콘솔에서 프로젝트 'Resume' 클릭 또는 연결 문자열 재확인 |
| CORS 에러 | ALLOWED_ORIGINS 불일치 | Vercel 도메인 정확히 추가 (프로토콜 `https://` 포함) |
| MCP 엔드포인트 401/403 | 인증 없음/권한 없음 | `mcp-caller` 서비스 계정에 `roles/run.invoker` 부여 확인 |
| MCP 서비스 시작 실패 | 카탈로그 검증 실패 | TERM_CARD 파일 검증 오류 확인 (`gcloud run services logs read mcp`) |
| 빌드 실패 | requirements.txt 의존성 | 로컬에서 `docker compose build`로 선검증 |
| Neon SSL 에러 | `sslmode=require` 누락 | 연결 문자열에 `?sslmode=require` 필수 |

---

## 11. 운영 환경 DB 초기화

운영 환경(Neon production branch) 배포 시 DB 스키마/테이블 초기화가 필요합니다. 별도 migration 프레임워크 도입 없이 현재 저장소 방식을 재사용합니다.

### 초기화 절차

```bash
# 1. Neon 콘솔에서 production branch 선택
# 2. SQL Editor에서 아래 스크립트 실행 (최초 1회)

# 세션 테이블
CREATE TABLE IF NOT EXISTS sessions (
    session_id UUID PRIMARY KEY,
    session_token_hash TEXT NOT NULL,
    anonymous_user_id_hash TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    last_activity_at TIMESTAMPTZ DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL,
    last_summary TEXT
);

# 메시지 테이블
CREATE TABLE IF NOT EXISTS messages (
    message_id UUID PRIMARY KEY,
    session_id UUID REFERENCES sessions(session_id),
    user_text TEXT NOT NULL,
    structured_json JSONB,
    validation_result JSONB,
    model_name TEXT,
    prompt_version TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

# Job 테이블
CREATE TABLE IF NOT EXISTS jobs (
    job_id UUID PRIMARY KEY,
    session_id UUID REFERENCES sessions(session_id),
    request_id TEXT NOT NULL,
    status TEXT NOT NULL,
    attempt INT DEFAULT 1,
    max_attempts INT DEFAULT 3,
    lease_expires_at TIMESTAMPTZ,
    failure_code TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);

# 검색 결과 테이블
CREATE TABLE IF NOT EXISTS search_results (
    id BIGSERIAL PRIMARY KEY,
    message_id UUID REFERENCES messages(message_id),
    role TEXT NOT NULL,
    term_id TEXT NOT NULL,
    pin_url TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

# 인덱스
CREATE INDEX IF NOT EXISTS idx_sessions_expires_at ON sessions(expires_at);
CREATE INDEX IF NOT EXISTS idx_messages_session_id ON messages(session_id);
CREATE INDEX IF NOT EXISTS idx_jobs_session_id ON jobs(session_id);
CREATE INDEX IF NOT EXISTS idx_search_results_message_id ON search_results(message_id);
```

> **참고**: 테이블 스키마는 `backend/services/storage.py` (구현 시)의 모델 정의와 동기화해야 합니다. 현재 저장소에 별도 migration 도구(Alembic 등)는 없으므로, 스키마 변경 시 위 SQL을 수정해 Neon 콘솔에서 직접 실행합니다.

### 자동 초기화 (향후 구현 시)

`backend/services/storage.py`의 `init_db()` 함수에서 위 테이블 생성을 수행하도록 구현하면, 앱 시작 시 자동으로 테이블이 생성됩니다.

```python
# backend/services/storage.py (구현 예정)
async def init_db() -> None:
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS sessions (...);
            -- 위 SQL과 동일
        """)
```

앱 시작 시 `await init_db()`를 호출하면 배포마다 수동 실행 불필요.

---

## 10. 무료 티어 한계 및 대비

| 리소스 | 무료 한계 | 초과 시 |
|---|---|---|
| Cloud Run | 월 200만 요청, 360만 vCPU-초, 180만 GiB-초 | 과금 ($0.000024/vCPU-초) |
| Neon | 0.5GB 스토리지, 1프로젝트 | 유료 플랜($19/월~) 또는 Supabase 무료(500MB) 이전 |
| Cloud Build | 월 120 빌드분 | 초과분 과금 |
| Artifact Registry | 0.5GB 스토리지 무료 | GB당 $0.10/월 |
| Vercel Hobby | 100GB 대역폭, 무제한 개인 프로젝트 | Pro 플랜($20/월) |

**팁**: Neon 대신 **Supabase 무료(500MB, PostgreSQL + Auth + Realtime)**도 대안. 연결 문자열만 바꾸면 됨.

Compose에서 프롬프트를 override할 때는 `INTERPRETER_PROMPT_PATH`와 `INTERPRETER_PROMPT_VERSION`을 함께 설정한다. 기존 v0 경로만 있는 `.env`는 버전도 `uhkegryo-interpreter-v0`으로 지정하거나 두 설정을 제거해 v4 기본 배포로 전환한다. 한 값만 지정하거나 파일의 Prompt 이름과 버전이 다르면 실행 전에 오류가 발생한다.
