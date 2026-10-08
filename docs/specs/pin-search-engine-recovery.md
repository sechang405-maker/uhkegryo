# Pin 검색 엔진 단일 호출

## Why
- 검색 차단과 timeout에 대비해 여러 외부 엔진을 차례로 호출하면 불필요한 요청이 늘어난다.
- 지표: Pinterest 엔진 호출 1회로 정상 Pin, 정상 빈 결과, 엔진 장애를 구분한다.
## Goal
- SearXNG Pinterest 엔진만 호출하고 다른 검색 엔진으로 fallback하지 않는다.
- 범위 밖: 차단/CAPTCHA 우회, 이미지 저장, URL 검증 완화, 결과 조작, 다른 검색 엔진 fallback.
## What
- Pinterest 엔진 응답에서 유효 Pin이 있으면 반환한다.
- Pinterest 엔진 정상 응답에서 유효 Pin이 없으면 PIN_RESULTS_EMPTY, 요청 또는 엔진 장애이면 PIN_SEARCH_UNAVAILABLE을 반환한다.
- 엔진 장애 응답에 유효 Pin이 포함되면 Pin을 보존하되 unavailable 표시를 유지한다.
## How
- `!pin`, images/json/en, 기존 suffix 및 HTTPS Pinterest 숫자 Pin 정규화를 유지한다. SearXNG Pinterest 엔진은 외부 `link`보다 원본 Pin ID로 canonical Pin URL을 만든다. `site:pinterest.com/pin`은 Pinterest 엔진 검색어에 전달하지 않는다.
- Pinterest 엔진 timeout 15초, provider 호출당 1회. worker의 기존 재시도 상한은 유지한다.
- SearXNG settings에서 Pinterest 엔진을 활성화하고 sidecar 내부 요청임을 나타내는 loopback X-Forwarded-For/X-Real-IP를 보낸다. limiter 보호는 해제하지 않는다.
## AC
- Given 활성 카드 검색 조각, When 검색, Then Pinterest 엔진 `!pin` 요청만 한 번 실행한다.
- Given Pinterest 엔진이 유효 Pin을 반환, When 검색, Then 검증된 Pin을 반환하고 다른 엔진을 호출하지 않는다.
- Given Pinterest 엔진 장애/정상 빈 결과, When 검색, Then 각각 unavailable/empty를 반환하고 다른 엔진을 호출하지 않는다.
- Given 외부/중복/비정상 Pin URL, When 어느 엔진에서 반환, Then 기존 필터·8개 상한이 유지된다.

엔진 선택 문법은 [SearXNG 공식 엔진 목록](https://docs.searxng.org/user/configured_engines.html)의 pin을 따른다.

- Given term-search HTTP 테스트가 Pinterest 엔진 장애를 모사, When 검색 실행, Then PIN_SEARCH_UNAVAILABLE을 검증한다.
