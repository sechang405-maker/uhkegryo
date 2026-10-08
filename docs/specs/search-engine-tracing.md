# Pinterest 검색 요청 트레이싱

## Why

- 로컬 개발자가 Pinterest 검색 지연과 실패 원인을 Job trace에서 확인해야 한다.
- 현재 searching span은 LLM, MCP, 검색과 Widget 시간을 묶어 엔진별 병목을 알 수 없다.
- 지표: 실행한 엔진의 순서, 요청 시간, 결과 수, 실패 분류를 trace에서 확인한다.

## Goal

- 기존 Job trace의 searching 아래 역할별 `pinterest-search-{role}` span을 기록한다.
- span output의 `engine_attempts`에 단일 Pinterest 엔진 요청의 latency_ms와 결과를 기록한다.
- 범위 밖: 동시성·worker 재시도 변경, 엔진별 별도 span, 배포, UI 변경.

## What

- Pinterest 엔진 요청 한 건을 기록한다. 검색 엔진 fallback은 실행하지 않는다.
- 빈 결과, 차단, 일시 중지, timeout, 잘못된 응답을 구분한다.
- 역할 span의 latency는 MCP 왕복과 Widget 조회를 포함한다. engine_attempts의 latency_ms는 SearXNG 요청과 결과 검증 시간이다.
- 병렬 역할은 서로 독립적인 기록을 사용한다. 관측 장애·잘못된 진단 값은 검색 결과를 바꾸지 않는다.
- 기존 MCP 응답에 진단 필드가 없어도 처리한다. 진단 정보는 LLM 메시지·Job 결과·DB에 포함하지 않는다.

## How

- 역할 span의 하위 시간 분리와 결과 API 측정은 [검색 지연 구간 분리](./search-latency-breakdown.md)를 따른다. 기존 engine_attempts 계약은 유지한다.
- provider에 선택적 engine_attempts 목록을 전달한다. monotonic clock으로 각 요청 시간을 측정한다.
- 기록 필드: engine, bang, latency_ms, pin_count, status(success/empty/unavailable), failure_reason(null/access_denied/suspended/captcha/rate_limited/timeout/upstream_error/malformed_response), fallback(bool).
- MCP search_pinterest_pins 응답은 기존 필드 외 `_search_trace` 배열을 추가한다. 이는 관측 전용 선택 필드다.
- worker는 역할 span을 열고 MCP 결과에서 `_search_trace`를 제거한 뒤 허용 필드·타입·범위만 Langfuse output에 기록한다. structuredContent와 content의 JSON text 두 응답 형식을 지원한다. 원문 오류, 외부 응답, 인증값, 썸네일 URL은 진단에 넣지 않는다.
- 역할 span input에는 승인된 role과 query_fragments만 기록한다. transport 오류는 원문 없이 exception 클래스 이름만 기록한다. Langfuse 장애는 기존 fail-open 경계를 따른다.

## AC

- Given Pinterest 검색 성공, When 검색, Then 한 건만 기록되고 fallback=false다.
- Given Pinterest 검색 차단, When 검색, Then 실패 분류·결과 수·0 이상 시간이 기록되고 다른 엔진은 호출하지 않는다.
- Given 빈 결과·timeout·잘못된 응답, When 검색, Then 해당 상태와 안전한 실패 분류가 기록되고 기존 결과 계약이 유지된다.
- Given 동시 역할 검색, When 실행, Then 역할별 진단이 섞이지 않는다.
- Given MCP 진단 응답, When worker 실행, Then 같은 trace의 역할 span에 진단이 기록되고 LLM 메시지에는 `_search_trace`가 없다.
- Given 관측 update 실패 또는 잘못된 진단 필드, When 기록, Then 검색 결과는 유지되고 승인하지 않은 필드는 전송하지 않는다.

검증 기록 (2026-10-06): 관련 provider·worker·병렬 검색·trace·MCP 회귀 테스트 56개 통과, git diff --check 통과. 로컬 API/MCP 재빌드 후 LLM 없이 실제 검색을 실행하고 Langfuse v2 Observations API에서 trace `53559252c8380299d6e64d334212c9e3`의 searching → pinterest-search-pose 연결과 엔진 진단을 확인했다. Google/DuckDuckGo suspended 후 Pinterest 성공(Pin 8개), 요청 시간 각각 10.357/9.225/921.299ms. 새 유료 LLM 호출과 운영 배포는 포함하지 않는다.
