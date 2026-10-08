# MCP SearXNG Pinterest Pin 검색

## Why

- **상황**: 검증된 TERM_CARD 검색 조각으로 Pinterest Pin 링크를 찾는 MCP 도구가 필요하다.
- **문제**: 별도 Cloud Run MCP 서비스가 API 서비스의 localhost SearXNG sidecar를 사용할 수 없다.
- **지표**: MCP 도구가 접근 가능한 SearXNG에 연결되고, Pin URL 검증과 기존 검색 상태 코드를 반환한다.

## Goal

- `search_pinterest_pins` 입력을 활성 TERM_CARD와 대조한 뒤 SearXNG Pinterest 엔진만 호출한다.
- 로컬 Compose에서는 `mcp`가 `searxng` 서비스에 연결하고, Cloud Run에서는 MCP 서비스의 SearXNG sidecar에 localhost로 연결한다.
- 역할별 worker 전환, LLM 도구 선택 및 재시도는 후속 worker 연동 Spec의 범위다.
- **범위 밖**: worker 연결, widget 조회 변경, 이미지 저장, term 카드 선택 변경.

## What

1. MCP client가 `search_pinterest_pins(role, query_fragments)`를 호출한다.
2. MCP 서버가 입력의 역할과 조각 배열이 활성 TERM_CARD와 정확히 일치하는지 확인한다. 불일치는 `INVALID_SEARCH_TERMS`로 거부하고 SearXNG를 호출하지 않는다.
3. 일치하면 `!pin {fragments} drawing`을 `categories=images`, `format=json`, `language=en`으로 검색한다.
4. HTTPS Pinterest host의 숫자 `/pin/{id}` 결과를 순서대로 중복 없이 최대 8개 반환한다.
5. 정상 빈 결과, 검색 장애 및 필수 설정 누락을 각각 `PIN_RESULTS_EMPTY`, `PIN_SEARCH_UNAVAILABLE`, `CONFIGURATION_ERROR`로 구분한다.

## How

- 입력은 허용 역할 enum과 비어 있지 않은 문자열 배열이며, 전체 배열이 활성 카드와 일치해야 한다.
- MCP 프로세스만 `SEARXNG_BASE_URL`을 사용한다. Compose 주소는 `http://searxng:8080`; Cloud Run MCP와 sidecar는 같은 네트워크 namespace에서 `http://localhost:8080`으로 통신한다.
- Cloud Run MCP Host는 실제 서비스 URL host를 `MCP_ALLOWED_HOST`로 등록하고, 외부 MCP 요청에는 별도 Cloud Run IAM 인증을 적용한다.
- Cloud Build는 기존 ingress가 이름 없으면 `mcp`로 명명해 설정을 교체하고, 이름이 있으면 그 ingress를 갱신한다. 두 경우 모두 `mcp` ingress 하나와 별도 SearXNG sidecar 하나를 구성하고 시작 순서를 revision annotation으로 지정한다. 이름 없는 설정 교체는 `--dry-run` 검증을 먼저 통과해야 한다.
- 검색 결과·Pin URL 검증과 실패 코드는 기존 `SearXNGPinterestSearchProvider` 계약을 따른다.

## AC

- **Given** 활성 카드의 역할과 검색 조각이 전달되면, **When** MCP 도구를 호출하면, **Then** SearXNG 이미지 엔진 검색 후 검증된 Pin을 최대 8개 반환한다.
- **Given** 역할 또는 조각이 활성 카드와 다르면, **When** 도구를 호출하면, **Then** `INVALID_SEARCH_TERMS`를 반환하고 SearXNG 요청은 발생하지 않는다.
- **Given** SearXNG가 정상 빈 결과 또는 장애를 반환하면, **When** MCP 도구가 응답하면, **Then** 각각 `PIN_RESULTS_EMPTY` 또는 `PIN_SEARCH_UNAVAILABLE`을 반환한다.
- **Given** Cloud Run MCP가 배포되면, **When** 유효한 IAM 인증 MCP client가 서비스 Host를 사용하면, **Then** Host 검사에서 차단되지 않으며 SearXNG sidecar 주소가 설정된다.
- **Given** 신규·이름 있는 기존·이름 없는 기존 Cloud Run 서비스 설정이 있으면, **When** Cloud Build가 MCP를 배포하면, **Then** 기존 ingress 하나와 SearXNG sidecar 하나만 구성하고 Host 허용값을 ingress에 설정한다.

엔진 장애 또는 유효 Pin 0건이면 다른 검색 엔진으로 대체하지 않고 [pin-search-engine-recovery.md](pin-search-engine-recovery.md)에 정의된 실패 코드를 반환한다.
