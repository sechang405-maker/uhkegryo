# UH케그려 — 캐주얼 캐릭터 일러스트 레퍼런스 해석 Agent

> 개인 비공개 실험 저장소입니다. `aihuman-7th/proj2-4`의 `main` 커밋 `1708bec`를 파일 스냅샷으로 가져왔습니다. 아래의 팀 배포·PR·평가 기록은 원본 프로젝트의 역사적 증거이며, 이 저장소의 실험 결과나 배포 완료를 뜻하지 않습니다. 별도 DB·API 키·배포 대상 없이 원본 서비스를 실험에 연결하지 마세요.

**원본 팀 배포(참고용, 이 저장소의 배포 아님):** [https://uhkegryo.vercel.app/](https://uhkegryo.vercel.app/)

> 전문 용어가 낯선 초보자가 텍스트로 묘사한 캐주얼 캐릭터의 **체형/소체, 포즈, 구도**를 기초 드로잉 용어와 역할별 Pinterest 탐색 계획으로 바꾸는 Agent입니다.

> **현재 상태: PostgreSQL job 저장, LLM → resolver → MCP 검색 → 응답 조립 worker, 세션 기억, 3D 용어 그래프와 결과·대화 UI 구현됨**
> `POST /api/agent`는 세션 쿠키와 queued job을 만들고, `GET /api/jobs/{job_id}`는 동일 세션의 job을 조회합니다. worker는 claim한 job을 LLM 해석·resolver 검증·Pinterest 검색·응답 조립까지 처리하고, 재시도와 lease 복구를 수행합니다. frontend는 입력·제출·polling, 완료 답변·용어·Pin 미리보기·대화 이력을 표시합니다. 실제 운영 브라우저 E2E는 별도 검증 대상입니다. Job trace와 generation 관측 코드는 구현됐습니다. PR #108에서 공용·로컬 합성 trace 수신을 검증했으며, 실제 LLM 요청 관측·원격 Prompt 운영·Dataset 연결은 미검증입니다. 별도 MCP 서비스의 `get_active_term_card` FastMCP 도구는 Cloud Run IAM으로 배포됐으며, 로컬·운영 MCP client 호출을 검증했습니다. 아래의 목표 구조와 계획 항목은 완료 기능으로 해석하면 안 됩니다.

## 한눈에 보기

| 항목 | 내용 |
| --- | --- |
| 핵심 사용자 | 캐주얼 캐릭터 일러스트를 시작했고 드로잉 전문 용어가 낯선 사용자 |
| 반복 문제 | 원하는 체형·포즈·구도를 일상어로만 검색해 넓은 결과를 반복 탐색한다. |
| 해결 방식 | 일상어를 구조화한 뒤, 용어 설명과 역할별 외부 탐색 링크를 함께 제공한다. |
| 팀 | UH케그려 (4조) |
| 현재 실행 가능 범위 | Docker Compose 기반 FastAPI `GET /health`, PostgreSQL 세션·Job API와 LLM worker, 카탈로그 시작 검증, MCP 도구 |

## 현재 개인 저장소 UI

### 3D 용어 그래프

- React와 SVG로 렌더링하는 고정 월드 좌표 기반 3D 방사형 그래프입니다. 화면 좌표를 따로 밀어내는 2D 배치가 아니라, 모든 노드와 직선 엣지가 하나의 카메라에서 함께 회전합니다.
- 카테고리 허브에서 기본 용어가 불규칙한 3D 방향과 거리로 뻗고, `+`를 누르면 해당 부모의 **직접 자식만** 같은 그래프 안에서 펼쳐집니다. 표시 그래프에서는 자식마다 대표 부모를 하나만 사용합니다.
- 드래그로 yaw/pitch를 회전하고, 마우스 휠로 안전 범위 안에서 확대·축소합니다. 노드 선택·펼침·hover는 고정 월드 좌표를 다시 계산하지 않습니다.
- 체형은 청록, 포즈는 주황, 구도는 보라, 투시는 초록 계열입니다. 자식은 같은 계열의 조금 밝은 색을 사용하며, 목록과 검색 결과 화면의 배지·테두리도 같은 카테고리 색을 공유합니다.
- 데스크톱은 3D 보기가 기본입니다. 모바일은 읽기 쉬운 목록으로 시작하지만 `3D 보기`로 전환할 수 있고, 사용자가 선택한 목록 보기도 유지됩니다. 실제로 과도하게 큰 합성 fan만 용어 누락을 막기 위해 목록으로 표시합니다.

현재 활성 카탈로그는 82개 용어입니다. 기본 그래프는 그중 36개를 보여 주며, 검수된 직접 자식 17개와 카테고리 허브 4개를 합친 57개가 현재 3D 그래프의 고정 배치 대상입니다. 나머지 활성 용어를 임의로 그래프에 추가하지 않습니다.

#### 그래프 조작

| 동작 | 결과 |
| --- | --- |
| 빈 배경 드래그 | 전체 그래프 회전 |
| 마우스 휠 | 확대·축소 |
| 원 클릭 | 실제 검색 조건 선택·해제 |
| 원 안 `+` / `−` | 직접 자식 펼치기·접기(조건 자동 선택 안 함) |
| `목록 보기` / `3D 보기` | 같은 선택·펼침 상태를 유지한 채 표현만 전환 |

깊이 차이 때문에 회전 중 화면에서 노드나 엣지가 겹쳐 보이는 것은 정상적인 3D 투영입니다. 검증 대상은 월드 공간의 노드 충돌과 직선 엣지가 무관한 노드의 3D 영역을 관통하는지 여부이며, 모든 카메라 각도에서 화면상 겹침이 전혀 없다고 보장하지 않습니다.

### 검색·대화·복구

- 그래프의 포커스와 실제 선택 조건을 분리합니다. `현재 용어만 검색`과 `선택 조건 전체 검색`은 서로 다른 범위를 명시하고, 부모를 펼치는 동작이 검색 조건을 자동으로 추가하지 않습니다.
- 일반·스케치·도형화 검색 모드를 카드별로 다시 실행할 수 있으며, 결과 화면은 역할별 배지와 카드 테두리를 카테고리 색으로 구분합니다. 이미지 자체에는 색 필터를 적용하지 않습니다.
- 저장된 이전 답변은 그 답변에 속한 레퍼런스를 다시 열 수 있습니다. 새 LLM 요청이나 검색을 만들지 않고 저장된 결과를 재사용합니다.
- 검색 job 상태 조회가 일시적으로 끊기면 제한된 자동 재시도 뒤 `상태 다시 확인`으로 같은 job을 이어 봅니다. 재확인은 새 검색 POST나 턴 사용량을 만들지 않습니다.
- 모바일에서는 검색 완료를 알리고 사용자가 명시적으로 결과 패널을 열 수 있습니다. 늦게 도착한 결과가 사용자가 이동한 패널이나 다른 대화를 강제로 덮지 않습니다.
- 용어 설명은 사용자용 한국어 정의를 사용하며, 내부 LLM 단서 질문을 설명 대체값으로 노출하지 않습니다. 접이식 조작 안내에서 선택·펼치기·검색·회전을 구분합니다.

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

## 프로젝트 상태와 후속 개발

팀 과제는 종료됐습니다. 아래 MVP·제출·배포 수치는 원본 팀 프로젝트의 당시 범위와 증거입니다. 개인 저장소의 후속 기능과 기술 선택은 작업별로 다시 결정할 수 있으며, 변경 전 현재 API/MCP 계약·데이터 보호·권리 경계를 확인하고 검증 결과를 별도로 기록합니다. 이 설명은 RAG·LangGraph 등 새 기능의 구현 또는 배포 승인을 뜻하지 않습니다.

## 원본 MVP 범위

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

SearXNG 검색 규칙은 [SearXNG Pinterest 검색 Spec](docs/specs/searxng-pinterest-search.md), widget 기반 Pin 미리보기·보관 경계는 [Pinterest 기능 Spec](docs/specs/pinterest-widget-crawler.md)을 단일 기준으로 사용합니다. 서버에는 JSON Search API가 활성화된 SearXNG 주소를 `SEARXNG_BASE_URL`로 설정해야 합니다. 용어 선택·설명·검색 조각은 구현 후 팀이 작성·검수한 TERM_CARD JSON 카탈로그만 사용합니다. 카탈로그는 시작 시 검증해 메모리에 로드하며 요청 중 파일을 다시 읽거나 DB에 적재하지 않습니다. Getty는 용어 조사 시 참고한 자료일 뿐, 서비스 데이터·사용자 화면·LLM 입력·런타임 조회에 포함하지 않습니다. 새 카드나 외부 자료는 출처·권리·품질을 사람이 검토하고 계약·평가를 갱신한 뒤에만 활성 데이터로 표시합니다. 검토하지 않은 데이터를 완료된 카탈로그로 주장하지 않습니다.

## API와 MCP 상태

| 항목 | 현재 상태 | 최종 목표 |
| --- | --- | --- |
| `GET /health` | 구현됨. `{"status":"ok"}` 반환 | Cloud Run 상태 확인 |
| `POST /api/agent` | PostgreSQL 영속화 구현됨. 세션 쿠키 발급·재사용, `202 + job_id` 반환 | 실제 환경 요청 증거 |
| `GET /api/jobs/{job_id}` | PostgreSQL 영속화 구현됨. 소유 job의 상태·완료 결과·실패 조회 | 실제 운영 UI 연결 검증 |
| DB 영속화·실제 worker | 구현됨. PostgreSQL job claim, LLM adapter·resolver·Pinterest provider·response assembler pipeline, retry·lease recovery | 실제 환경 실행 증거 |
| LLM 해석·resolver 연동 | 구현됨. worker가 활성 TERM_CARD를 LLM에 전달하고 resolver·검색 결과를 조립해 저장 | 실제 모델 품질 평가 |
| Pinterest 검색 실행 | worker 연결 구현됨. SearXNG Pinterest 엔진 검색·widget enrichment 코드와 단위 테스트 존재 | 실제 SearXNG 인스턴스 연결·검색 결과 검증 |
| Next.js UI | 입력·제출·polling, 3D 용어 그래프, 목록·결과 카테고리 색상, 모바일 결과 안내, 저장 레퍼런스 재열기와 상태 재확인 구현됨 | 실제 외부 검색·다양한 기기에서 지속 검증 |
| `/docs` | FastAPI 기본 문서에서 확인 가능 | 요청·응답 모델 및 오류 응답 확인 |
| `/mcp` | `backend.mcp.main:app`에 마운트된 Streamable HTTP endpoint를 Cloud Run IAM으로 배포함. 무인증 `403`, 인증된 도구 목록·`found`·`not_found` 호출을 검증함. [호출 증거](docs/mcp-client-evidence.md) | Streamable HTTP endpoint와 도구 호출 증거 |
| TERM_CARD JSON 카탈로그 | 구현됨. API·MCP 시작 시 검증 후 역할별 활성 카드를 메모리에 로드 | 요청 중 재읽기·DB 적재 없이 활성 카드를 조회 |
| MCP 접근 제어 | Cloud Run IAM 검증됨. 최종 `roles/run.invoker`는 `mcp-caller` 서비스 계정에만 부여됨 | 내부 호출자만 접근 |

`/mcp`를 공개 데모 API처럼 무제한 노출하지 않습니다. 실제 배포 전 Cloud Run IAM, 연결 방법, 도구 목록과 외부 클라이언트 호출 결과를 함께 검증·기록합니다.

## 신규 사용자를 위한 Docker Compose 실행

현재 저장소는 비공개입니다. 저장소 소유자가 GitHub 접근 권한을 부여했거나 별도로 전달한 소스 사본을 가진 사람만 내려받을 수 있습니다. 이 절차는 저장소를 공개하거나 사용 권한을 새로 부여하지 않습니다.

### 준비물

- Docker Desktop 또는 Docker Engine + Docker Compose v2
- GitHub 접근 권한이 있는 경우 Git
- 사용자 본인의 OpenRouter API key

기본 실행은 다음 컨테이너를 시작합니다.

| 서비스 | 역할 | 호스트 주소 |
| --- | --- | --- |
| `frontend` | Next.js UI와 API proxy | `http://127.0.0.1:3100` |
| `api` | FastAPI, job worker, migration 적용 후 시작 | `http://127.0.0.1:8000` |
| `app-db` | 애플리케이션 PostgreSQL과 영속 볼륨 | 컨테이너 내부 전용 |
| `mcp` | 검색 도구 gateway | `http://127.0.0.1:8001` |
| `searxng` | 이미지 검색 | `http://127.0.0.1:8080` |

Langfuse와 그 저장소는 기본 실행에 포함되지 않으며 `observability` profile을 선택할 때만 시작됩니다.

### 처음 실행

```powershell
git clone https://github.com/sechang405-maker/proj2-4-rag-langgraph-lab.git
cd proj2-4-rag-langgraph-lab
Copy-Item .env.example .env
```

macOS/Linux에서는 마지막 명령 대신 `cp .env.example .env`를 사용합니다.

`.env`에서 `OPENROUTER_API_KEY=` 뒤에 **본인의 키**를 입력합니다. 실제 키나 개인 DB URL을 Git에 커밋하지 마세요. 기본 로컬 DB를 쓸 때 다른 필수 값은 없습니다.

```powershell
docker compose up --build -d
docker compose ps
```

`db-migrate`가 내부 PostgreSQL이 준비될 때까지 기다린 뒤 001~현재 migration을 순서대로 적용합니다. 성공한 migration은 다시 적용되지 않으며, migration이 실패하면 API와 frontend가 시작되지 않습니다.

다음 주소를 확인합니다.

```powershell
(Invoke-RestMethod -Uri 'http://127.0.0.1:8000/health')
(Invoke-RestMethod -Uri 'http://127.0.0.1:3100/service-health')
```

두 응답 모두 `status`가 `ok`여야 합니다. UI는 `http://127.0.0.1:3100`에서 엽니다. 이 health 확인은 DB migration과 서비스 연결을 확인하지만 유료 LLM 요청이나 외부 검색 결과까지 검증하지는 않습니다.

### 종료, 재시작, 업데이트

```powershell
# 컨테이너만 종료. app_postgres_data 등 named volume은 유지됩니다.
docker compose down

# 다시 시작
docker compose up -d

# 저장소 업데이트 후 이미지 재빌드
git pull --ff-only
docker compose up --build -d
```

`docker compose down -v`는 로컬 DB와 관측 데이터를 삭제하므로 데이터 삭제를 의도한 경우가 아니면 사용하지 마세요.

### 포트와 외부 PostgreSQL

3100, 8000, 8001, 8080이 이미 사용 중이면 `.env`의 `FRONTEND_PORT`, `API_PORT`, `MCP_PORT`, `SEARXNG_PORT`를 변경합니다. 서비스는 기본적으로 `127.0.0.1`에만 바인딩됩니다.

기존 Neon 또는 다른 PostgreSQL을 사용하려면 `.env`의 `DATABASE_URL`에 전체 연결 문자열을 입력합니다. `db-migrate`와 API가 같은 URL을 사용합니다. 이 경우에도 로컬 `app-db` 컨테이너는 안전한 기본 구성으로 함께 시작되지만 애플리케이션 데이터에는 사용되지 않습니다.

### 선택: Langfuse 관측 스택

```powershell
docker compose --profile observability up --build -d
```

Langfuse UI는 기본 `http://127.0.0.1:3000`입니다. `.env.example`의 Langfuse 값은 localhost 개발 예시이며 공유 서버의 비밀값이 아닙니다. 공유 환경에서는 모두 새 임의 값으로 교체해야 합니다. Langfuse에서 organization/project와 API key를 만든 뒤 `LANGFUSE_APP_URL=http://langfuse-web:3000`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`를 설정하고 API를 다시 생성합니다.

```powershell
docker compose up -d --force-recreate api
```

### 문제 해결

```powershell
docker compose config --quiet
docker compose ps
docker compose logs db-migrate api frontend
```

- `OPENROUTER_API_KEY` 오류: `.env`에 본인의 키가 비어 있지 않은지 확인합니다.
- API가 시작되지 않음: `db-migrate` 로그와 `DATABASE_URL`을 확인합니다.
- frontend의 `/service-health` 실패: `api`가 healthy인지 확인합니다. 브라우저용 public URL이 아니라 컨테이너 내부 `http://api:8000`으로 proxy됩니다.
- 포트 충돌: `.env`의 포트 값만 바꾸고 무관한 호스트 프로세스를 일괄 종료하지 않습니다.
- 검색 실패: `searxng`와 `mcp` 로그를 확인합니다. 외부 검색 사이트 상태에 따라 실제 결과는 달라질 수 있습니다.

이 구성은 개인 컴퓨터의 localhost 개발 실행용입니다. 인터넷 공개 배포를 위한 TLS, 인증, secret manager, 방화벽 정책을 제공하지 않습니다. 저장소 라이선스와 공개 여부도 이 패키징 변경에서 결정하지 않았습니다.

## 기존 수동 개발 실행

아래 절차는 외부 Neon DB와 호스트 Node.js, 기본 Langfuse 스택을 직접 조합하던 기존 개발 경로입니다. 신규 사용자는 위의 완결된 기본 Compose 실행을 권장합니다.

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
git clone https://github.com/sechang405-maker/proj2-4-rag-langgraph-lab.git
cd proj2-4-rag-langgraph-lab
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
cd proj2-4-rag-langgraph-lab\frontend
npm ci
npm run dev -- --port 3001
```

브라우저에서 `http://localhost:3001`을 열어 1~500자 입력의 유효성 검사, `POST /api/agent` 제출, job polling 상태 표시까지 확인합니다. 현재 UI는 답변·질문·용어·Pin 미리보기·대화 이력을 표시합니다. demo가 아닌 실제 API 모드에서 새 요청으로 확인합니다.

### 준비된 개인 로컬 프로필

[`docs/local-codex.md`](./docs/local-codex.md)의 개인 로컬 프로필을 이미 준비한 환경에서는 기존 DB·검색 컨테이너와 볼륨을 재사용해 API 8000과 production frontend 3100을 시작할 수 있습니다. 이 경로는 `.env.local-codex`, `.env.local-profile`, frontend production build가 이미 준비되어 있어야 하며 새 DB를 만들거나 migration을 자동 실행하지 않습니다.

```powershell
cd frontend
npm ci
npm test
npm run build
cd ..
./scripts/start-local.ps1
```

준비가 끝나면 다음 세 주소가 응답해야 합니다.

| 주소 | 기대 결과 |
| --- | --- |
| `http://127.0.0.1:3100/` | Next.js UI |
| `http://127.0.0.1:3100/service-health` | `{"status":"ok"}` |
| `http://127.0.0.1:8000/health` | `{"status":"ok"}` |

`start-local.ps1`은 이미 3100에서 듣고 있는 프런트를 재사용합니다. 새 production build 뒤 화면이 이전 버전이라면 먼저 `Get-NetTCPConnection -LocalPort 3100 -State Listen`으로 리스너를 확인하고, 그 PID가 이 저장소의 `next start -p 3100`인지 명령줄과 작업 경로를 검증한 뒤 해당 프런트만 재시작합니다. 포트 번호만 보고 무관한 Node 프로세스를 일괄 종료하지 않습니다. 서버 HTML이 참조하는 `/_next/static/chunks/*.js`가 현재 `.next` 빌드의 청크인지 확인하면 브라우저 캐시와 실행본 불일치를 구분할 수 있습니다.

종료는 다음 명령으로 합니다.

```powershell
docker compose down
```

frontend 개발 서버도 해당 PowerShell 창에서 `Ctrl+C`로 중지합니다. `docker compose down`은 named volume을 삭제하지 않습니다.

> 아직 새 환경에서 이 전체 절차를 끝까지 실행한 실측은 없습니다. 특히 최종 코드의 실제 LLM·MCP·Pinterest 결과와 브라우저 렌더링은 별도 검증 대상입니다. Langfuse 인프라 기동 확인은 LLM trace 기록 확인과 별개입니다. 원격 Prompt 등록·Dataset 연결·대시보드 측정을 완료한 뒤 새 환경에서 절차를 다시 검증하고 결과를 갱신합니다.

## 원본 제출 기준과 당시 검증

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

## 개인 후속 개발

원격 소유자와 기본 브랜치를 확인하고 변경 목적·영향·검증 근거를 남깁니다. 이 개인 저장소에서는 팀원 approve, PR, 강사 확인, 과제 제출 마감, 400줄 상한이 필수 절차가 아닙니다. API/MCP 호환성, 데이터·비밀정보 보호, 외부 자료의 권리와 약관은 계속 확인합니다. 원본 팀의 공로와 기록은 보존합니다. [운영 기준](./AGENTS.md)과 [원본 협업 기록](./docs/github-workflow.md)을 참고하세요.

## 원본 배포와 데모 기록

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
