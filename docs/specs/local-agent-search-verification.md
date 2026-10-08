# 로컬 Agent 통합 답변·검색 연동 확인

## Why

- **페르소나·상황**: 최신 main을 받아 로컬 UI에서 실제 레퍼런스를 검색하는 팀원.
- **문제**: 오래된 API 이미지에는 `answer_text`가 없고, 새 검색 경로의 MCP·SearXNG가 실행되지 않으면 화면과 검색 결과를 함께 확인할 수 없다. `/health` 성공만으로 전체 요청 성공을 판단할 수 없다.
- **측정 지표**: 프론트 제출 → DB job → LLM 해석 → 검색 → 통합 답변·Pin 반환까지 실제 요청 한 건의 종결 상태와 결과를 기록한다.

## Goal

- 기존 구현을 최신 이미지로 실행하고 실제 API 경로에서 통합 답변과 검색 결과를 확인한다.
- 재현에 필요한 로컬 설정과 검증 범위를 공유한다.
- **범위 밖**: 검색 의미 품질 개선, 모델 기본값 변경, 애플리케이션 코드 변경, DB migration, 전체 평가셋 통과율 측정, 운영 배포.

## What

1. 로컬 `.env`에 Compose 필수값과 `SEARXNG_SECRET`을 준비한다.
2. #103~#105 병합 상태를 확인하고, 같은 코드에서 API·MCP 이미지를 빌드해 API·MCP·SearXNG를 실행한다.
3. API 응답 스키마, MCP health·도구 목록, SearXNG JSON 검색을 확인한다. MCP 준비 확인 실패 시 job을 제출하지 않는다.
4. 프론트에서 실제 요청을 제출하고 같은 세션 쿠키로 종결까지 polling한다.
5. 반환된 통합 답변, 용어, Pin 링크, 썸네일 응답을 확인한다.

| 상황 | 확인·처리 |
| --- | --- |
| 실행 중인 API·MCP 이미지가 오래됨 | `restart`만 하지 않고 같은 코드에서 두 이미지를 `--build` 후 컨테이너를 다시 만든다. |
| MCP health만 성공하고 검색 도구가 없음 | API 컨테이너에서 실제 MCP transport로 도구 목록을 조회해 `search_pinterest_pins` 등록을 확인한다. 등록 전에는 job을 제출하지 않는다. |
| `SEARXNG_SECRET` 누락 | 로컬 `.env`에 임의의 긴 비밀값을 넣고 Compose 설정 검증을 다시 실행한다. 비밀값을 공유 문서나 커밋에 넣지 않는다. |
| 모델 일반 호출은 되지만 엄격한 JSON Schema 요청은 404 | 동일한 `response_format`과 provider 조건을 처리할 endpoint가 있는 모델로 로컬 설정을 맞춘다. 일반 호출 성공만으로 호환성을 판단하지 않는다. |
| 기존 이력에 `answer_text`가 없음 | 과거 답변이 자동 생성되지는 않는다. 최신 API에서 새 요청으로 확인한다. |
| 이미지 검색이 비거나 실패함 | `partial_result`와 검색 사유 코드를 확인한다. 통합 답변 누락과 이미지 검색 문제를 각각 확인한다. |

## How

### 로컬 설정·기동

Neon 개발 DB, OpenRouter key, Langfuse 내부 비밀값은 기존 `.env.example`의 계약을 따른다. 아래 재현 절차는 준비된 개발 DB를 전제로 하며, 공유 DB의 migration을 자동 실행하지 않는다.

**적용 전제**: 아래 MCP 절차는 #103~#105가 main에 병합된 코드에서 실행한다. 2026-10-02 재검증 시작 시점에 세 PR은 아직 open이고 main은 `1e7a921`이었다. 후보 코드의 별도 검증과 병합 후 main 검증을 구분한다.

이번 실측에서는 로컬 `.env`의 다음 설정을 사용했다. 저장소의 모델 기본값은 변경하지 않는다.

```dotenv
LLM_MODEL=openai/gpt-4.1-mini
INTERPRETER_PROMPT_PATH=./prompts/uhkegryo-interpreter-v1.md
INTERPRETER_PROMPT_VERSION=uhkegryo-interpreter-v1
```

`SEARXNG_SECRET`은 별도로 생성해 로컬 `.env`에만 설정한다. 새 Compose는 API의 `MCP_BASE_URL=http://mcp:8001/mcp`, MCP의 `SEARXNG_BASE_URL=http://searxng:8080`, `MCP_ALLOWED_HOST=mcp:8001`을 설정한다. MCP 진입점은 `mcp_server.server:app`이다.

```powershell
# 저장소 루트: 기존 Langfuse 저장 서비스가 실행 중인 환경
docker compose config --quiet
docker compose up -d --build --no-deps api mcp searxng
```

`--no-deps`는 나열한 세 서비스만 실행하므로 Langfuse와 저장 서비스는 먼저 실행되어 있어야 한다. 이 명령에는 MCP를 명시해 API와 같은 최신 코드로 함께 빌드한다.

job 제출 전에 MCP health가 `status=ok`, `catalog_valid=true`, `active_cards_count>0`인지 확인한다.

```powershell
$health = Invoke-RestMethod http://127.0.0.1:8001/health
if ($health.status -ne "ok" -or $health.catalog_valid -ne $true -or $health.active_cards_count -le 0) {
    throw "MCP catalog is not ready"
}
@'
import asyncio
from backend.shared.config import get_settings
from backend.services.mcp_tool_gateway import McpToolGateway

async def main():
    tools = await McpToolGateway(mcp_url=get_settings().mcp_base_url).list_tools()
    names = {tool["name"] for tool in tools}
    assert "search_pinterest_pins" in names, "MCP search tool is not ready"
    print("MCP search tool ready")

asyncio.run(main())
'@ | docker compose exec -T api python -
```

health 요청과 transport·도구 조회가 모두 성공해야 다음 요청 단계로 진행한다. 컨테이너가 running이라는 사실만으로 준비됐다고 판단하지 않는다.

`.env`의 모델 설정만 바꾼 뒤에는 다음 명령으로 API 컨테이너를 다시 만든다.

```powershell
docker compose up -d --no-deps api
```

별도 터미널에서 프론트를 실행한다.

```powershell
cd frontend
npm run dev -- --hostname 127.0.0.1 --port 3001
```

### 요청·확인 경로

- API health: `GET http://127.0.0.1:8000/health` → 200.
- 실행 중인 API의 `GET /openapi.json`에서 `AgentResult.properties.answer_text`가 있는지 확인한다.
- SearXNG: `GET http://127.0.0.1:8080/search`에 `q=!pin contrapposto drawing`, `categories=images`, `format=json`, `language=en`을 URL 인코딩해 전달한다. `results[].url`이 Pinterest Pin ID 기반 canonical URL인지, `unresponsive_engines`를 확인한다.
- 프론트 origin `http://127.0.0.1:3001`에서 `POST /api/agent`에 아래 입력과 UUID `Idempotency-Key`를 보낸다. 응답 쿠키를 유지해 `GET /api/jobs/{job_id}`를 polling한다. 브라우저 입력창을 사용하면 프론트가 이 처리를 수행한다.
- 종결 후 `result.answer_text`, `reference_plan.terms`, 역할별 `pins`, `reason_codes`를 확인한다. 이미지 URL은 HEAD 응답의 200과 이미지 Content-Type으로 확인하며 이미지 파일은 내려받지 않는다.

검증 입력:

> 마른 체형의 캐릭터가 한쪽 다리에 체중을 싣고 서 있는 자세 레퍼런스를 찾아줘.

### 2026-10-02 병합 전 직접 검색 기록 (새 MCP 경로의 근거 아님)

- 코드 기준: `1e7a921` (main, PR #102 병합 상태).
- 아래 수치는 #103~#105 병합 전 worker가 직접 SearXNG provider를 호출한 기록이다. LLM tool calling → MCP 검색 경로의 성공 근거로 사용하지 않는다.
- 기존 API 이미지에는 `answer_text`가 없음을 OpenAPI와 컨테이너 스키마에서 확인했다. 최신 이미지에서는 해당 필드가 있다.
- 당시 `openai/gpt-6-luna` 일반 호출은 200이었지만, 앱의 엄격한 JSON Schema 요청은 OpenRouter 404 (`No endpoints found that can handle the requested parameters`)로 실패했다. 이 관측을 모든 provider·미래 시점의 모델 지원 여부로 일반화하지 않는다.
- 로컬 모델을 `openai/gpt-4.1-mini`로 변경한 후 실제 프론트 프록시를 거친 요청 한 건이 `completed / success`, `reason_codes=[]`, `failure=null`로 종결됐다.
- `answer_text` 336자, `body_slim`과 `pose_contrapposto` 각각 Pin 8개, 서로 다른 Pin 링크 총 16개를 받았다.
- 썸네일 16개 모두 HEAD 응답 200 및 이미지 Content-Type을 확인했다.
- 프론트 `answerForJob()`의 반환값이 API의 `answer_text`와 일치하고, 호환 안내 문구가 반환되지 않았다. 갤러리 helper가 용어 2개와 표시 가능한 썸네일 16개를 반환했다.
- SearXNG 직접 검색은 결과 20개와 `unresponsive_engines=[]`를 반환했다. 검색 결과 수는 외부 서비스 상태에 따라 달라질 수 있다.
- 이는 요청·검색 연결 검증이다. 브라우저 DOM의 실제 렌더링 검증, 30문항 평가, 이미지의 의미 적합성·검색 품질 채점은 수행하지 않았다.
- 저장소에는 비밀값, DB 연결 문자열, 세션 쿠키, 전체 응답 원문, 썸네일 URL을 추가하지 않는다.

### #103~#105 병합 후 검증 상태

- **미완료**: 확인 시점에 #103~#105가 아직 미병합이므로 병합 후 main에서 실행한 요청은 없다. 기존 16개 Pin 수치를 새 경로의 수치로 옮기지 않는다.
- 병합 후 실제 main SHA를 기록하고 위 명령으로 API·MCP를 함께 다시 빌드한다. MCP health·`search_pinterest_pins` 도구 등록 확인 후 같은 입력을 새 job으로 제출한다.
- 새 job의 종결 상태, `answer_text` 길이, 역할별 Pin·썸네일 수, 검색 사유 코드와 오류를 따로 기록한다. MCP 서버의 실제 tool 처리 기록도 확인해 직접 검색 경로와 구분한다.
- 이후 별도 후보 코드 검증을 수행하더라도 그 결과를 병합 후 main 검증으로 표시하지 않는다.

### 2026-10-02 MCP 후보 코드 검증 (미병합, 병합 후 검증을 대체하지 않음)

- 코드 기준: #105 head `ddd7f937ca32ec29be4921010fd07c55bcff21e8`. #103 head `56d6bf4`와 #104 head `458f13f`가 이 커밋의 조상임을 Git에서 확인했다.
- 별도 Compose 프로젝트 `pr106-mcp-check`에서 같은 후보 이미지로 API·MCP를 실행했다. API·MCP의 이미지 digest가 일치했다. 기존 로컬 서비스와 worker의 job claim이 섞이지 않도록 별도 PostgreSQL 컨테이너를 사용했다.
- 격리 DB에만 migration을 적용했다. 공유 Neon DB와 기존 로컬 API에는 후보 코드를 적용하지 않았다. 테스트 전용 구성 파일·비밀값은 저장소 밖에 두었다.
- API `18000`, MCP `18001`, SearXNG `18080` 포트에서 검증했다. 이 격리 구성은 위의 병합 후 기본 포트 재현 환경과 다르다.
- MCP health: `status=ok`, `catalog_valid=true`, `active_cards_count=82`. API 컨테이너에서 MCP transport로 `get_active_term_card`, `search_pinterest_pins` 등록을 확인했다.
- 같은 검증 입력을 후보 API에 새로 제출했다. 결과는 `completed / success`, `reason_codes=[]`, `failure=null`, `answer_text` 255자였다.
- `body_slim`, `pose_contrapposto` 각각 Pin 8개와 썸네일 8개를 반환했다. 총 16개 썸네일의 HEAD 응답은 모두 200 및 이미지 Content-Type이었다.
- MCP 서버 로그에서 실제 `CallToolRequest` 처리 4건을 확인했다. 후보 worker는 MCP gateway의 검색 결과를 역할별로 검증하는 경로를 사용하며 직접 provider 검색 경로를 사용하지 않는다.
- 이 검증은 후보 API → LLM tool calling → MCP → SearXNG → widget → 결과 반환의 연결 확인이다. 후보 frontend 프록시·브라우저 렌더링·Langfuse 수집·검색 의미 품질은 검증하지 않았다.
- 검증 후 테스트 전용 컨테이너와 네트워크를 종료한다. 실제 병합 후 main 검증은 위의 미완료 상태를 유지한다.

## AC

- **Given** 필수 로컬 설정, **When** `docker compose config --quiet` 실행, **Then** 비밀값을 출력하지 않고 설정 검증이 통과한다.
- **Given** 최신 API 이미지, **When** 실행 중인 OpenAPI 조회, **Then** `AgentResult`에 `answer_text` 필드가 있다.
- **Given** #103~#105 병합 코드와 기존 저장 서비스, **When** 기동 명령 실행, **Then** API·MCP가 같은 코드로 빌드되고 MCP·SearXNG가 함께 실행된다.
- **Given** MCP 기동, **When** health와 API 컨테이너의 MCP 도구 목록 조회, **Then** 유효 카탈로그와 `search_pinterest_pins` 등록을 확인한다. 확인 실패 시 job을 제출하지 않는다.
- **Given** 준비 확인을 마친 MCP·SearXNG·프론트·API, **When** 새 검증 입력 제출, **Then** 같은 쿠키로 종결 상태·통합 답변·검색 결과와 실제 MCP tool 처리를 확인한다.
- **Given** 병합 전 기록과 후보 코드 검증, **When** 결과 문서화, **Then** 각각의 코드 SHA와 경로를 구분하고 병합 후 검증 미완료를 성공으로 표시하지 않는다.
- **Given** 문서의 실측 결과, **When** 검증 범위를 읽음, **Then** 한 건의 연결 성공을 검색 품질이나 전체 평가 통과율로 해석하지 않는다.
