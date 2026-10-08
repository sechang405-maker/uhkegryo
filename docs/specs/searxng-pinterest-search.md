# SearXNG 이미지 엔진 Pinterest Pin 검색 provider

## Why

- **페르소나·상황**: 검증된 TERM_CARD로 Pinterest 원본 Pin을 찾는 백엔드 개발자.
- **문제**: Pinterest 검색 HTML 파서는 렌더링 변화와 차단에 취약하다.
- **측정 지표**: Pinterest 엔진 JSON 결과에서 유효한 Pin URL을 순서대로 최대 8개 반환한다.

## Goal

- SearXNG Search API의 Pinterest 엔진만 사용한다. 이미지 카테고리만 사용한다.
- 활성 카드의 `query_fragments`에 `drawing`을 붙인다.
- URL이 HTTPS Pinterest 호스트의 숫자 Pin 경로인 결과만 반환한다.
- Worker가 이 provider를 사용해 widget 조회와 결과 조립으로 연결한다.
- 사용되지 않는 Pinterest HTML·Playwright 크롤러 코드, 테스트와 의존성을 제거한다.
- **범위 밖**: 이미지 파일 저장.

## What

1. provider가 `!pin` 검색 문법과 `categories=images`, `format=json`, `language=en`을 요청한다.
2. JSON의 `results[].url`만 읽어 Pinterest Pin ID와 정규화된 URL을 만든다.
3. 중복 ID를 제거하고 결과 순서대로 최대 8개 반환한다.
4. Pinterest 엔진의 정상 응답에 유효 Pin이 없으면 `PIN_RESULTS_EMPTY`, 엔진 장애이면 `PIN_SEARCH_UNAVAILABLE`로 반환한다. 다른 검색 엔진으로 대체 호출하지 않으며 오류 원문은 로그에 남기지 않는다.
5. Worker는 검증된 카드의 검색 조각을 provider에 전달하고 결과를 widget 조회 및 응답 조립에 사용한다.

## How

- `SearXNGPinterestSearchProvider(base_url=...)`는 `GET {base_url}/search`를 `httpx`로 호출하며 제한시간은 15초다.
- 검색어는 `!pin {" ".join(query_fragments)} {suffix}`이다.
  suffix는 기본 `drawing`이며 `sketch`, `mannequinization`도 허용한다.
  worker의 기본 검색은 그대로 drawing이다. 카드 재검색 endpoint는
  [term-search-api.md](term-search-api.md)를 따른다.
- SearXNG Docker image는 공식 Pinterest engine이 반환하는 외부 원본 `link` 대신 `result.id`로 canonical Pin URL을 만든다. 따라서 backend에는 Pin ID가 보존된 `/pin/{ASCII digits}` URL만 전달된다.
- `https`와 `pinterest.com` 또는 하위 도메인, `/pin/{ASCII digits}` 경로만 허용한다.
- 반환 URL은 `https://www.pinterest.com/pin/{id}/`로 정규화한다.
- base URL 누락은 `CONFIGURATION_ERROR`이고, 이미지 URL·본문·제목은 읽거나 저장하지 않는다.
- Worker의 `SEARXNG_BASE_URL`은 Compose에서 `http://searxng:8080`, Cloud Run에서는 API와 같은 서비스의 비공개 SearXNG sidecar 주소 `http://localhost:8080`으로 설정한다.
- Cloud Run은 `searxng/Dockerfile`로 JSON 설정과 canonical Pin URL 패치가 적용된 SearXNG 이미지를 빌드한다. SearXNG 컨테이너는 외부 ingress를 받지 않으며 API와 같은 Cloud Run 인스턴스 안에서만 접근한다.
- `SEARXNG_SECRET`은 Cloud Run sidecar에 Secret Manager 환경변수로 전달한다.
- SearXNG는 `SEARXNG_SECRET` 환경변수로 설정 파일의 기본 secret key를 덮어쓴다. settings YAML은 환경변수 템플릿 치환을 하지 않는다.
- Cloud Run은 SearXNG sidecar의 TCP startup probe가 8080 포트에서 성공한 뒤 API ingress 컨테이너를 시작한다. API ingress는 `--depends-on=searxng`로 이를 보장한다.
- 응답의 `search_url`은 Pinterest에서 추가 탐색을 위한 별도 링크다. 반환된 `pins`는 SearXNG Pinterest 엔진 검색 결과이며, `search_url`이 해당 Pin 목록을 재현한다고 보장하지 않는다.

## AC

- **Given** 활성 카드 검색 조각이 있을 때, **When** provider가 검색하면, **Then** Pinterest 엔진만 한 번 호출한다.
- **Given** Pinterest와 외부 도메인 URL이 섞인 JSON일 때, **When** 파싱하면, **Then** 숫자 Pin URL만 고유 순서대로 최대 8개 반환한다.
- **Given** 검색 결과가 없을 때, **When** 파싱하면, **Then** `PIN_RESULTS_EMPTY`를 반환한다.
- **Given** SearXNG가 HTTP 200과 빈 결과 및 Pinterest 엔진 `unresponsive_engines` 오류를 반환할 때, **When** provider가 처리하면, **Then** `PIN_SEARCH_UNAVAILABLE`을 반환하고 worker가 기존 재시도 횟수만큼 검색을 시도한다.
- **Given** 주소 누락·HTTP 오류·잘못된 JSON일 때, **When** 검색하면, **Then** 주소 누락은 `CONFIGURATION_ERROR`, 그 외 실패는 `PIN_SEARCH_UNAVAILABLE`로 처리한다.
- **Given** 유효한 LLM 선택과 활성 카드가 있을 때, **When** Worker가 job을 처리하면, **Then** 카드 검색 조각으로 SearXNG를 호출하고 검증된 Pin 결과를 widget 조회와 응답 조립에 전달한다.
- **Given** Worker의 검색 경로가 SearXNG로 전환됐을 때, **When** 런타임 의존성을 설치하면, **Then** 기존 Pinterest HTML 크롤러와 Playwright 설치가 필요하지 않다.
- **Given** Cloud Build가 API를 Cloud Run에 배포할 때, **When** API와 SearXNG sidecar를 시작하면, **Then** API는 `http://localhost:8080`으로 검색하고 SearXNG 컨테이너는 외부 ingress 없이 실행된다.
- **Given** Cloud Run이 API와 SearXNG sidecar를 시작할 때, **When** SearXNG TCP startup probe가 성공하기 전이면, **Then** API ingress는 시작되지 않는다.

검색 단일 엔진·canonical Pin URL·빈 결과/장애 판정·loopback 헤더와 추가 AC는 [pin-search-engine-recovery.md](pin-search-engine-recovery.md)를 따른다. 검색 호출당 엔진 요청은 15초 timeout으로 한 번이며 기존 worker 재시도 횟수는 유지한다.
