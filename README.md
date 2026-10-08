# UH케그려 — 캐주얼 캐릭터 일러스트 레퍼런스 해석 Agent

**배포 사이트:** [https://uhkegryo.vercel.app/](https://uhkegryo.vercel.app/)

> 전문 용어가 낯선 초보자가 텍스트로 묘사한 캐주얼 캐릭터의 **체형/소체, 포즈, 구도**를 기초 드로잉 용어와 역할별 Pinterest 탐색 계획으로 바꾸는 Agent입니다.

> **현재 상태: PostgreSQL job 저장, LLM → resolver → MCP 검색 → 응답 조립 worker, 결과·대화 UI 구현됨**
> `POST /api/agent`는 세션 쿠키와 queued job을 만들고, `GET /api/jobs/{job_id}`는 동일 세션의 job을 조회합니다. worker는 claim한 job을 LLM 해석·resolver 검증·Pinterest 검색·응답 조립까지 처리하고, 재시도와 lease 복구를 수행합니다. frontend는 입력·제출·polling, 완료 답변·용어·Pin 미리보기·대화 이력을 표시합니다. 실제 운영 브라우저 E2E는 별도 검증 대상입니다. Job trace와 generation 관측 코드는 구현됐습니다. PR #108에서 공용·로컬 합성 trace 수신을 검증했으며, 실제 LLM 요청 관측·원격 Prompt 운영·Dataset 연결은 미검증입니다. 별도 MCP 서비스의 `get_active_term_card` FastMCP 도구는 Cloud Run IAM으로 배포됐으며, 로컬·운영 MCP client 호출을 검증했습니다. 아래의 목표 구조와 계획 항목은 완료 기능으로 해석하면 안 됩니다.

## 한눈에 보기

| 항목 | 내용 |
| --- | --- |
| 핵심 사용자 | 캐주얼 캐릭터 일러스트를 시작했고 드로잉 전문 용어가 낯선 사용자 |
| 반복 문제 | 원하는 체형·포즈·구도를 일상어로만 검색해 넓은 결과를 반복 탐색한다. |
| 해결 방식 | 일상어를 구조화한 뒤, 용어 설명과 역할별 외부 탐색 링크를 함께 제공한다. |
| 팀 | UH케그려 (4조) |
| 현재 실행 가능 범위 | Docker Compose 기반 FastAPI `GET /health`, PostgreSQL 세션·Job API와 LLM worker, 카탈로그 시작 검증, MCP 도구 |

## 팀원

| 이름 | GitHub | 역할 | 한마디 |
| --- | --- | --- | --- |
| 오세창 | @sechang405-maker | 도메인 경험·용어 검토 | 잘 부탁드립니다! |
| 김호섭 | @SZversion | MCP, 아키텍처 | 잘 부탁드립니다! |
| 윤태현 | @surf7978 | 백엔드, 에이전트 출력 | 잘 부탁드립니다! |

## 문제와 도메인 경험

프리랜서 캐주얼 캐릭터 일러스트레이터로 약 3년 활동한 오세창의 작업 경험에서 출발했습니다. 의뢰 이미지나 텍스트 설명만으로 캐릭터를 그릴 때, 하나의 이미지에서 모든 조건을 찾기보다 **체형/소체 → 지지점과 포즈 → 시점·원근·배치 → 세부 표현** 순서로 조건을 나눠 여러 레퍼런스를 병렬로 확인했습니다.

초보자는 “한쪽 다리에 힘을 준 자연스러운 자세”, “상체가 넓고 다리가 긴 캐릭터”, “아래에서 올려다보는 구도”처럼 묘사하지만, 이를 `contrapposto`, `inverted triangle body type`, `low angle` 또는 `foreshortening` 같은 탐색 가능한 용어로 바꾸기 어렵습니다. 이 Agent는 그 번역과 탐색 계획 수립을 돕습니다.

## 목표 사용자 흐름

1. 사용자가 만들고 싶은 캐릭터를 일상어로 입력합니다.
2. Agent가 체형/소체, 포즈, 시점, 원근, 배치를 구분해 해석합니다.
3. 각 조건을 쉬운 말과 드로잉 용어로 설명하고, 확신하지 못한 조건은 질문 또는 한계로 표시합니다.
4. 서버가 선택된 역할별 `query_fragments`에 `drawing`을 붙여 SearXNG Pinterest 엔진 검색을 수행하고, 유효한 Pin 링크 최대 8개를 찾습니다. SearXNG 엔진은 외부 원본 링크 대신 Pin ID로 canonical Pin URL을 반환합니다. 각 Pin ID는 widget endpoint로 조회해 원격 썸네일 URL을 현재 응답에만 넣습니다.
5. UI는 서버가 반환한 원격 썸네일을 원본 Pin 링크로 표시합니다. 서비스는 이미지 파일·썸네일 URL·Pin 본문 등 부가 메타데이터를 저장하지 않습니다.
6. 사용자는 하나의 ‘정답 이미지’가 아니라 역할별 레퍼런스를 조합해 러프를 시작합니다.

### 입력과 목표 출력 예시

| 입력 | 목표 해석 예시 |
| --- | --- |
| “한쪽 다리에 힘 주고 상체는 살짝 틀어진 마른 캐릭터” | `body: slim`, `pose: contrapposto`, `pose: torso twist` |
| “낮은 곳에서 올려다보는 앉은 캐릭터” | `pose: seated`, `view: low angle`, `perspective: foreshortening` |

용어 해석은 사용자의 의도를 확인하는 제안이며, 신체 비율이나 포즈를 단정하는 판정이 아닙니다.

## MVP 범위

### 제공할 것

- 1~500자 텍스트 설명의 구조화 해석
- 체형/소체, 포즈, 구도(`view`, `perspective`, `layout`)의 역할 분리
- 전문 용어의 초보자용 설명과 불확실성 표시
- 선택된 역할별 Pinterest 원격 썸네일 미리보기와 원본 Pin 링크(역할별 최대 8개)
- 세션 이력에 포함된 Pin ID·URL·상태 유지와 썸네일 URL·이미지의 비저장
- 팀 검수 TERM_CARD JSON 카탈로그의 용어·설명·검색 조각

### 제공하지 않을 것

- 이미지 생성, 편집, 업로드 이미지 분석, 특정 작가 화풍 복제
- Pinterest 이미지 파일·썸네일·메타데이터의 저장, 재게시 또는 브라우저 직접 크롤링
- 단일 이미지가 모든 조건에 맞는다고 보장하는 추천
- 문서를 청크로 검색해 답변에 주입하는 RAG

제외 범위와 이유는 [NOT_BUILD.md](./NOT_BUILD.md)에서 확인할 수 있습니다.

## 목표 아키텍처

```text
사용자 UI
  -> POST /api/agent (PostgreSQL에 세션·queued job 저장, 서버 세션 쿠키 발급·재사용, 202 + job_id)
  -> GET /api/jobs/{job_id} polling (PostgreSQL에서 소유권 확인 후 상태·결과 조회)
Job worker / retry·lease recovery (LLM → resolver → MCP search → response assembly 구현, 외부 E2E 미측정)
  -> LLM: 일상어를 허용된 term_id와 역할로 구조화
  -> 결정론 코드: Pydantic 검증, 역할 순서, 허용 ID, URL 인코딩
  -> FastMCP: TERM_CARD JSON 카탈로그의 활성 카드 정보를 구조화 조회
  -> MCP search_pinterest_pins -> SearXNG Pinterest 엔진 검색 (Pin ID → canonical Pin URL) -> Pin URL 검증 -> widget 조회 -> 역할별 최대 8개 {pin_id, pin_url, thumbnail_url, status} 반환
  -> UI: 원격 썸네일을 원본 Pin 링크로 표시
```

| 계층 | 담당 책임 |
| --- | --- |
| LLM | 일상어의 의미 해석, 조건 충돌·모호성 인식, 허용된 구조화 선택 생성 |
| 결정론 코드 | Pydantic 스키마 검증, 허용 `term_id`, 역할 순서, URL 인코딩, 실패 응답 |
| FastMCP | 시작 시 검증해 메모리에 로드한 TERM_CARD JSON 카탈로그의 활성 카드만 조회하고, Getty 데이터·외부 어휘 API·SPARQL·웹 호출은 하지 않음 |
| UI | 입력 안내, 로딩·실패 안내, 용어·한계·외부 링크 표시 |

LLM은 링크를 임의로 만들거나 데이터 출처를 지어내지 않습니다. 링크 생성과 출력 검증은 코드가 맡습니다.

## 도메인 데이터와 출처 경계

| 구분 | 계획된 역할 | 출력에 보이는 정보 |
| --- | --- | --- |
| TERM_CARD JSON 카탈로그 | `index.json`과 다섯 역할 JSON으로 이루어진 팀 검수 런타임 단일 원본 | term ID, 설명, query fragment, 검수 상태 |
| Pinterest | 사용자가 원본을 직접 확인할 외부 탐색 대상 | 원본 Pin 링크와 응답 전용 원격 썸네일 미리보기 |

SearXNG 검색 규칙은 [SearXNG Pinterest 검색 Spec](docs/specs/searxng-pinterest-search.md), widget 기반 Pin 미리보기·보관 경계는 [Pinterest 기능 Spec](docs/specs/pinterest-widget-crawler.md)을 단일 기준으로 사용합니다. 서버에는 JSON Search API가 활성화된 SearXNG 주소를 `SEARXNG_BASE_URL`로 설정해야 합니다. 용어 선택·설명·검색 조각은 구현 후 팀이 작성·검수한 TERM_CARD JSON 카탈로그만 사용합니다. 카탈로그는 시작 시 검증해 메모리에 로드하며 요청 중 파일을 다시 읽거나 DB에 적재하지 않습니다. Getty는 용어 조사 시 참고한 자료일 뿐, 서비스 데이터·사용자 화면·LLM 입력·런타임 조회에 포함하지 않습니다. 자체 카드와 권리 검토 기준은 팀 승인을 거쳐야 하며, 승인되지 않은 데이터를 완료된 카탈로그로 주장하지 않습니다.

## API와 MCP 상태

| 항목 | 현재 상태 | 최종 목표 |
| --- | --- | --- |
| `GET /health` | 구현됨. `{"status":"ok"}` 반환 | Cloud Run 상태 확인 |
| `POST /api/agent` | PostgreSQL 영속화 구현됨. 세션 쿠키 발급·재사용, `202 + job_id` 반환 | 실제 환경 요청 증거 |
| `GET /api/jobs/{job_id}` | PostgreSQL 영속화 구현됨. 소유 job의 상태·완료 결과·실패 조회 | 실제 운영 UI 연결 검증 |
| DB 영속화·실제 worker | 구현됨. PostgreSQL job claim, LLM adapter·resolver·Pinterest provider·response assembler pipeline, retry·lease recovery | 실제 환경 실행 증거 |
| LLM 해석·resolver 연동 | 구현됨. worker가 활성 TERM_CARD를 LLM에 전달하고 resolver·검색 결과를 조립해 저장 | 실제 모델 품질 평가 |
| Pinterest 검색 실행 | worker 연결 구현됨. SearXNG Pinterest 엔진 검색·widget enrichment 코드와 단위 테스트 존재 | 실제 SearXNG 인스턴스 연결·검색 결과 검증 |
| Next.js UI | 입력·제출·polling 구현됨 | 결과·질문·Pin 링크·대화 UI 구현, 운영 화면 검증 필요 |
| `/docs` | FastAPI 기본 문서에서 확인 가능 | 요청·응답 모델 및 오류 응답 확인 |
| `/mcp` | `backend.mcp.main:app`에 마운트된 Streamable HTTP endpoint를 Cloud Run IAM으로 배포함. 무인증 `403`, 인증된 도구 목록·`found`·`not_found` 호출을 검증함. [호출 증거](docs/mcp-client-evidence.md) | Streamable HTTP endpoint와 도구 호출 증거 |
| TERM_CARD JSON 카탈로그 | 구현됨. API·MCP 시작 시 검증 후 역할별 활성 카드를 메모리에 로드 | 요청 중 재읽기·DB 적재 없이 활성 카드를 조회 |
| MCP 접근 제어 | Cloud Run IAM 검증됨. 최종 `roles/run.invoker`는 `mcp-caller` 서비스 계정에만 부여됨 | 내부 호출자만 접근 |

`/mcp`를 공개 데모 API처럼 무제한 노출하지 않습니다. 실제 배포 전 Cloud Run IAM, 연결 방법, 도구 목록과 외부 클라이언트 호출 결과를 함께 검증·기록합니다.

## 로컬 실행

현재 재현 절차의 계약은 [로컬 개발 재현 Spec](./docs/specs/local-development-reproduction.md)을 기준으로 합니다. 아래 절차는 API health와 frontend 입력·제출·polling까지의 현재 구현 범위를 실행합니다. **결과 UI는 구현되어 있으며 최종 버전의 실제 Pinterest·MCP·Langfuse·브라우저 E2E는 별도 검증 대상입니다.**

### 사전 준비

- Docker Desktop 또는 Docker Engine과 Docker Compose v2
- Git
- Node.js **20.9 이상**과 npm (frontend 실행용)
- Neon 개발 DB의 `DATABASE_URL`과 OpenRouter `OPENROUTER_API_KEY`를 본인의 `.env`에 준비합니다. 실제 URL·key를 저장소에 넣지 않습니다.
- 로컬 Langfuse 실행을 위해 `.env.example`의 Langfuse 내부 비밀값을 설정합니다. 저장 서비스별 비밀번호는 서로 다른 임의 hex 값으로 생성하고, `LANGFUSE_ENCRYPTION_KEY`는 64자리 hex 값으로 지정합니다.
- 로컬 SearXNG 실행을 위해 `SEARXNG_SECRET`에 임의의 긴 값을 설정합니다. API 내부 주소는 `http://searxng:8080`, 호스트 접근 주소는 `http://localhost:8080`입니다. 자세한 계약은 [로컬 SearXNG Compose Spec](./docs/specs/local-searxng-compose.md)을 참고합니다.
- 앱의 `DATABASE_URL`은 Neon 개발 DB를 사용하며, Langfuse는 별도 Compose PostgreSQL을 사용합니다. migration은 API startup에서 자동 실행되지 않습니다.

### PowerShell

```powershell
git clone https://github.com/aihuman-7th/proj2-4.git
cd proj2-4
Copy-Item .env.example .env
# .env에 DATABASE_URL, OPENROUTER_API_KEY, Langfuse 내부 비밀값을 채운 뒤 실행
docker compose up --build -d
```

Compose가 기동된 뒤, **job을 제출하기 전에** API 컨테이너에서 migration을 한 번 실행합니다. 이 명령은 `.env`의 `DATABASE_URL`에 연결하며, 값을 출력하지 않습니다.

```powershell
@'
import asyncio
import asyncpg

from backend.db.migrate import migrate
from backend.shared.config import get_settings


async def main():
    connection = await asyncpg.connect(get_settings().database_url)
    try:
        await migrate(connection)
    finally:
        await connection.close()


asyncio.run(main())
'@ | docker compose exec -T api python -
```

다음으로 API와 Langfuse health를 확인합니다.

| 주소 | 현재 기대 결과 |
| --- | --- |
| `http://localhost:8000/health` | `{"status":"ok"}` |
| `http://localhost:8000/docs` | FastAPI 자동 문서 |
| `http://localhost:3000` | 로컬 Langfuse UI. 가입 후 organization/project를 만들고 API key를 `.env`의 `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`에 입력 |

Compose API 컨테이너는 기본적으로 Langfuse에 `http://langfuse-web:3000`으로 연결합니다. 공용 서버 사용 시 `LANGFUSE_APP_URL`과 해당 프로젝트 키를 설정합니다. GCP 배포·전환 명령·발표 후 정리는 [Langfuse 운영 가이드](./docs/langfuse-operations.md)를 따릅니다. worker의 job trace lifecycle 코드는 구현됐지만, 실제 LLM 관측 데이터·원격 Prompt 등록·Dataset 연결·대시보드 측정은 별도 검증 대상입니다.

기동 후 PowerShell에서 설정과 health를 확인합니다. worker는 호스트 포트를 공개하지 않으므로 컨테이너 내부에서 검사합니다.

```powershell
docker compose config --quiet
(Invoke-RestMethod -Uri 'http://localhost:8000/health')
(Invoke-WebRequest -Uri 'http://localhost:3000/api/public/health').StatusCode
docker compose exec -T langfuse-worker sh -c 'wget -S -O- "http://$(hostname -i):3030/api/health"'
```

API health의 기대 본문은 `{"status":"ok"}`입니다. 두 Langfuse health endpoint는 `200`을 반환해야 하며, worker 검사 응답 본문은 `{"status":"ok"}`입니다. `/health`는 API liveness 확인이며 Neon DB migration, OpenRouter 호출, Pinterest 검색, Langfuse trace 기록까지 검증하지는 않습니다.

API와 별도로, 새 PowerShell 창에서 frontend를 시작합니다. Langfuse UI가 3000을 사용하므로 Next.js는 **3001** 포트를 사용합니다.

```powershell
cd proj2-4\frontend
npm ci
npm run dev -- --port 3001
```

브라우저에서 `http://localhost:3001`을 열어 1~500자 입력의 유효성 검사, `POST /api/agent` 제출, job polling 상태 표시까지 확인합니다. 현재 UI는 답변·질문·용어·Pin 미리보기·대화 이력을 표시합니다. demo가 아닌 실제 API 모드에서 새 요청으로 확인합니다.

종료는 다음 명령으로 합니다.

```powershell
docker compose down
```

frontend 개발 서버도 해당 PowerShell 창에서 `Ctrl+C`로 중지합니다. `docker compose down`은 named volume을 삭제하지 않습니다.

> 아직 새 환경에서 이 전체 절차를 끝까지 실행한 실측은 없습니다. 특히 최종 코드의 실제 LLM·MCP·Pinterest 결과와 브라우저 렌더링은 별도 검증 대상입니다. Langfuse 인프라 기동 확인은 LLM trace 기록 확인과 별개입니다. 원격 Prompt 등록·Dataset 연결·대시보드 측정을 완료한 뒤 새 환경에서 절차를 다시 검증하고 결과를 갱신합니다.

## 제출 기준 설정과 실제 검증

배포 구성·환경 변수 예시는 `LLM_MODEL=openai/gpt-4.1-mini`, `INTERPRETER_PROMPT_VERSION=uhkegryo-interpreter-v4`, v4 파일 경로를 함께 사용합니다. Cloud Run 이미지 경로는 `/app/prompts/uhkegryo-interpreter-v4.md`, 직접 Python은 `./prompts/uhkegryo-interpreter-v4.md`입니다. 기존 `.env`의 명시적 override도 세 값을 함께 맞춥니다. 구성 변경은 실제 클라우드 배포 완료를 뜻하지 않습니다.

과거 실제 모델 평가 40/40은 이전 작업 트리의 참고 결과입니다. 당시 프롬프트·어댑터 지문이 현재 PR과 달라 현재 배포 후보의 품질 통과 근거로 사용할 수 없습니다. 현재 PR의 동일 평가 재실행과 운영·정성 검증은 남아 있습니다. [평가 리포트](EVAL_REPORT.md)와 [실제 서비스 검증 절차](docs/service-validation-guide.md)에서 근거·미검증 범위를 확인합니다. `scripts/run_live_eval.py`는 검색 fixture와 Langfuse 비활성화를 사용하므로 외부 E2E에는 실제 API/브라우저 경로를 사용합니다.

## 환경 변수와 보안

필요한 변수명은 [.env.example](./.env.example)에만 공개합니다. 실제 값은 로컬 `.env` 또는 배포 환경의 Secret Manager에만 저장합니다.

- `.env`, API 키, 토큰, 서비스 계정 파일, 사용자 원문 이미지·개인정보를 커밋하지 않습니다.
- 키가 노출되면 Git 이력 삭제만으로 충분하지 않으므로 즉시 폐기·재발급합니다.
- 브라우저 UI는 LLM SDK 또는 비밀값을 직접 호출하지 않습니다.

## 평가와 운영 지표

최종 평가는 정상·경계·실패 유도 케이스를 포함한 최소 30건의 평가셋으로 수행합니다. 동일한 평가셋으로 한 가지 변경 후 다시 실행해 회귀를 확인합니다.

| 지표 | 현재 값 | 최종 기록 위치 |
| --- | --- | --- |
| 평가셋 품질 점수 | 현재 PR 미검증; 과거 참고 기대값 30/30 + 대조 10/10 (검색 fixture) | [EVAL_REPORT.md](./EVAL_REPORT.md) |
| 계약 준수율 | 미측정 | `EVAL_REPORT.md` |
| p50 / p95 지연 | 과거 참고 fixture 평가 4.61초 / 9.89초; 현재 PR·운영 미측정 | `EVAL_REPORT.md` |
| 요청당 평균 비용 | 미측정 | `EVAL_REPORT.md` |
| LLM·MCP 오류율 | 미측정 | `EVAL_REPORT.md` |

평가 문항과 판정 기준은 [evals/README.md](./evals/README.md), 실제 개선 전후 결과·실패 사례·Keep/Discard 판단은 [EVAL_REPORT.md](./EVAL_REPORT.md)에 남깁니다.

## 프로젝트 문서

| 문서 | 내용 |
| --- | --- |
| [PRD](./docs/PRD.md) | 제품 요구사항, 사용자 흐름, 범위와 수용 기준 |
| [SDD](./docs/SDD.md) | 시스템 아키텍처, 데이터 흐름, 검증·비동기 처리 설계 |
| [도메인 프로필](./docs/domains/illustration-reference/domain-profile.md) | 사용자, 업무 경험, 경쟁 서비스, 범위와 데이터 출처 |
| [경쟁 서비스 분석](./docs/domains/illustration-reference/competitive-analysis.md) | 실제 시작 흐름 비교, 차별점과 조사 한계 |
| [설계 문서](./docs/domains/illustration-reference/design.md) | LLM·결정론 코드·MCP의 책임 분리와 폴백 설계 |
| [API 계약](./docs/specs/api-contract.md) | `POST /api/agent`, 비동기 job 상태, 완료 결과, worker 실패·재시도 및 LLM JSON 계약 |
| [로컬 개발 재현](./docs/specs/local-development-reproduction.md) | clone 뒤 API·migration·frontend를 현재 구현 범위까지 시작하는 절차 |
| [로컬 Langfuse Compose](./docs/specs/local-langfuse-compose.md) | 로컬 Langfuse와 필수 저장 서비스 구성 |
| [로컬 SearXNG Compose](./docs/specs/local-searxng-compose.md) | 로컬 SearXNG 서비스·JSON API 설정 |
| [SearXNG Pinterest 검색](./docs/specs/searxng-pinterest-search.md) | Pinterest 단일 엔진 검색 요청·Pin URL 검증·실패 처리 계약 |
| [MCP 계약](./docs/specs/mcp-contract.md) | JSON 카탈로그 기반 `get_active_term_card` 도구의 입력·출력·접근 제어 |
| [NOT_BUILD.md](./NOT_BUILD.md) | MVP에서 의도적으로 만들지 않는 기능과 이유 |
| [EVAL_REPORT.md](./EVAL_REPORT.md) | 관측, 프롬프트 운영, 평가, 비용·지연, 출시 게이트 |
| [evals/](./evals/) | 평가셋과 판정 기준 |
| [작업 티켓](./docs/work-tickets.md) | 역할 분담·의존·일정을 포함한 전체 작업 목록 |
| [docs/SCAFFOLD.md](./docs/SCAFFOLD.md) | 저장소 폴더별 작성 안내 |

## 팀과 협업

1. `main`에는 직접 push하지 않고, 개인 브랜치에서 PR을 만듭니다.
2. PR은 팀원 1명 이상의 approve 뒤에 사람이 merge합니다.
3. 기능 구현 전 `docs/specs/{feature-name}.md`에 Why, Goal, What, How, AC를 작성합니다.
4. API 키·비밀번호·`.env`는 절대 커밋하지 않습니다.
5. 강사 확인이 필요한 질문은 Issue에 남기고 강사를 멘션합니다.

```powershell
git switch main
git pull
git switch -c feat/<작업내용>
# 작업 및 검증 후
git add <변경한-파일>
git commit -m "feat: <변경 내용>"
git push -u origin feat/<작업내용>
```

## 배포와 데모

| 제출 증거 | 상태 |
| --- | --- |
| 사용자 UI URL | 미배포 |
| Cloud Run Agent API URL | 미배포 |
| 외부 MCP client 연결·도구 호출 증거 화면 | 카드 조회 운영 검증 기록 있음; 최신 검색 경로 화면 정리 필요 |
| Langfuse 대시보드 스크린샷 | 합성 trace 수신 검증 있음; 실제 요청 화면 정리 필요 |
| 정상·실패 경로 데모 영상 | 미제작 |

배포와 평가가 끝나면 실제 URL·실행 날짜·모델·프롬프트 버전·데이터셋 버전만 기록합니다. 추정 수치나 아직 존재하지 않는 URL은 적지 않습니다.

## 대화 기억 변경

대화 기억 백엔드: 익명 쿠키 소유자와 여러 대화를 분리하고, /api/sessions 생성·목록·열람·이력 조회를 제공한다. /api/agent는 선택적 session_id를 받는다. 최근 6개 기록·현재 조건·요약을 전달하고 과거 기록 기반 회상 답변에 원본 job 출처를 붙인다. 적용 전 003_conversation_owners.sql migration이 필요하며 startup에서 자동 적용하지 않는다. 운영 적용·실제 모델 품질 평가는 별도이고 UI는 이번 범위에 포함하지 않는다.
