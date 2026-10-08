# 홈 카드·카테고리 재검색 API

## Why

초보 일러스트 사용자가 홈 카드를 누르거나 일반·스케치·도형화를 선택하면 UI는
`POST /api/term-search`를 호출한다. 서버 endpoint가 없어 실제 재검색이 실패한다.
성공 기준은 세 접미사의 검색어 일치와 활성 카드 이외의 검색 요청 0건이다.

## Goal

- 기존 SearXNG provider와 Pinterest widget으로 카드 하나의 `TermResult`를 반환한다.
- `drawing`, `sketch`, `mannequinization` 검색과 반환 URL의 접미사를 일치시킨다.
- LLM·DB·job·세션·검색 이력·이미지·썸네일 저장은 제외한다.
- UI와 worker의 기본 drawing 검색 동작은 변경하지 않는다.

## What

홈 카드 클릭은 기본 drawing 검색, 카테고리 선택은 지정한 접미사로 재검색한다.
활성 카드의 설명과 관찰 지점을 유지하고 원래 순서의 Pin을 최대 8개 반환한다.
0건과 검색 장애를 구분한다. UI는 실패·빈 결과에서 기존 이미지를 유지한다.
없는/비활성 ID는 404, 직접 검색 금지 ID는 409, 잘못된 본문은 422로 거부한다.

## How

- 요청: `POST /api/term-search`, JSON `{term_id: string(1..120), suffix?:
  drawing|sketch|mannequinization}`. 기본 suffix는 drawing. 추가 필드는 거부한다.
- 응답: HTTP 200 `TermResult`. 역할·라벨·설명은 시작 시 로드된
  `app.state.catalog`의 활성 카드와 feedback만 사용한다. 사용자 검색어·URL은 받지 않는다.
- 검색: `SearXNGPinterestSearchProvider`에 카드 query_fragments와 검증한 suffix를
  전달한다. `!pin {fragments} {suffix}`으로 검색하고
  `PinterestWidgetClient`로 원격 썸네일을 조회한다. 카드 조각 자체는 수정하지 않는다.
- 반환 search_url은 기존 Pinterest URL builder에 같은 suffix를 전달한다.
  Pinterest 직접 검색 페이지와 SearXNG Pinterest 엔진의 Pin 검색 결과가 같음을 보장하지 않는다.
- 정상 0건은 `PIN_RESULTS_EMPTY`, 엔진/통신 장애와 전체 25초 timeout은
  `PIN_SEARCH_UNAVAILABLE`로 반환한다. 설정 누락은 503과 고정 detail 안내를 반환한다.
- 프로세스/app당 동시 도구 요청은 2건. 대기열 없이 추가 요청은 429와
  `Retry-After: 1`을 반환한다. 종결·예외·취소·timeout 모두 슬롯을 반환한다.
- 쿠키·Idempotency-Key는 필요 없다. 세션 발급, DB, LLM, trace와 영속화는 호출하지 않는다.
  응답은 `Cache-Control: no-store`이며 썸네일은 현재 응답에만 포함한다.
- #87 검색 provider가 선행 의존성이다. 분산 rate limit·worker 재시도·배포는 제외한다.

## AC

- AC-01: Given 활성 카드, When 기본/세 접미사로 요청, Then 실제 provider 검색어와
  search_url의 suffix가 같고 카드 메타데이터·최대 8개 Pin·응답 전용 썸네일을 반환한다.
- AC-02: Given 없는/비활성/직접 검색 금지 ID 또는 잘못된 suffix/추가 검색어,
  When 요청, Then 각각 404/404/409/422이며 검색과 widget을 호출하지 않는다.
- AC-03: Given 정상 0건 또는 엔진/통신 장애, When 요청, Then 200 응답의
  reason_codes가 각각 PIN_RESULTS_EMPTY 또는 PIN_SEARCH_UNAVAILABLE이다.
- AC-04: Given 도구가 25초 이상 지연되거나 설정이 없음, When 요청,
  Then 각각 장애 TermResult 또는 503이며 내부 오류·secret은 반환하지 않는다.
- AC-05: Given 두 검색이 진행 중, When 세 번째 요청, Then 즉시 429이며
  기존 요청 완료·취소·실패 후 새 요청이 가능하다.
- AC-06: Given 실제 FastAPI 앱, When 카드 검색, Then DB·LLM·job·세션·trace를
  호출하지 않고 Set-Cookie가 없으며 응답은 no-store이고 카탈로그를 변경하지 않는다.

검증 (2026-10-02): AC 기반 HTTP 테스트 24 passed, 전체 backend 테스트
421 passed / 22 skipped, git diff --check 통과. 검색·widget 응답은 fixture로
검증했다. 로컬 SearXNG(127.0.0.1:8080)에 연결할 수 없어 외부 검색은 미검증이다.
