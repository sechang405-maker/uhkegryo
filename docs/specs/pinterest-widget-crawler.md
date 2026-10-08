# Pinterest 검색 결과·Widget 조회

Widget 결과 조립과 완료 Job 응답의 세부 계약은 [pinterest-widget-results.md](./pinterest-widget-results.md)를 따른다.

## Why

선택된 TERM_CARD의 검색 조각으로 외부 레퍼런스 링크와 응답 전용 미리보기를 제공해야 한다. 검색 호출은 [SearXNG Pinterest 검색 Spec](./searxng-pinterest-search.md)에 따라 Pinterest 엔진을 사용한다. 사용자는 역할별 원본 Pin 링크를 열어 레퍼런스를 확인하고, 서비스는 이미지 파일을 보관하지 않는다.

## Goal

- 서버 SearXNG 검색 provider가 Pinterest 엔진 결과에서 역할별 Pin ID와 `pin_url`을 수집한다.
- 모든 수집 Pin ID는 `https://widgets.pinterest.com/v3/pidgets/pins/info/?pin_ids={pin_id}`로 조회해 이미지 URL을 얻는다.
- 세션·job 이력에는 결과의 `pin_id`, `pin_url`, `status`만 포함하고, `thumbnail_url`과 이미지 바이트는 저장하지 않는다.

Pinterest API v5, `GET /v5/pins/{pin_id}`, Pinterest 페이지 직접 크롤링, 이미지 다운로드·재게시, 외부 결과의 LLM 입력은 범위 밖이다.

## What

1. resolver는 LLM이 고른 활성 TERM_CARD의 `query_fragments`만 검색 provider에 전달한다. SearXNG provider는 검색어를 `!pin {query_fragments} drawing`으로 만든다. 사용자 원문이나 LLM 자유 텍스트는 추가하지 않는다.
2. SearXNG Pinterest 엔진은 upstream result ID로 canonical Pin URL을 만들며, provider는 결과에서 역할별 최대 8개의 고유 Pin ID와 원본 `pin_url`을 수집한다.
3. 수집한 각 Pin ID에 widget endpoint를 요청한다. 응답의 `images` 항목 중 가장 큰 면적의 URL을 `thumbnail_url`로 사용한다.
4. widget 응답에 이미지 URL이 없거나 widget·원본 Pin에 접근할 수 없으면 해당 결과는 `status="deleted"`, `thumbnail_url=null`이다.
5. widget 응답의 이미지 URL은 현재 API 응답에만 넣는다. 세션·job 이력, 로그, trace, 카탈로그에는 저장하지 않는다.
6. 검색 페이지의 일시 실패는 작업 13의 검색 provider 재시도 대상이다. 재시도 소진 뒤 유효 카드가 있으면 `completed + partial_result`와 `PIN_SEARCH_UNAVAILABLE`을 반환한다. 개별 widget 조회 실패는 해당 Pin만 `deleted`로 처리한다.

## How

- Provider 계약 단계(PR-47)는 `PinterestProvider.search(role, query_fragments)` 비동기 메서드로 고정한다. `role`은 `Role`, `query_fragments`는 활성 카드에서 온 읽기 전용 `tuple[str, ...]`이며 결과는 기존 `RoleSearchOutcome`이다. 검색 결과의 Pin 타입은 기존 `PinResult`를 재사용한다.
- `FakePinterestProvider`는 역할별로 미리 주입한 `RoleSearchOutcome`의 복사본을 반환한다. 미설정 역할은 `KeyError`로 실패해 테스트 데이터 누락을 숨기지 않는다. 이 단계는 Pinterest·widget HTTP, Playwright, 검색 URL 생성, DB·trace·로그 저장을 수행하지 않는다.
- SearXNG 검색과 widget 조회는 서버에서만 수행하며 Next.js UI·일반 브라우저는 검색 또는 widget endpoint를 직접 호출하지 않는다.
- SearXNG 검색 요청 timeout은 15초, widget 요청 timeout은 10초다.
- 검색 요청과 검색어 조립은 [SearXNG Pinterest 검색 Spec](./searxng-pinterest-search.md)을 따른다. 예를 들어 `pose_gesture` 카드의 조각이 `gesture drawing`, `action line reference`이면 요청 검색어는 `!pin gesture drawing action line reference drawing`이다.
- SearXNG URL에서 HTTPS, Pinterest 도메인, 숫자 Pin ID를 모두 확인한 결과만 후보로 사용한다. 중복 Pin ID는 역할 안에서 하나만 유지한다.
- 결과가 없으면 `pins=[]`, `reason_codes=["PIN_RESULTS_EMPTY"]`를 반환한다.
- 수집한 Pin의 widget 요청 실패, 차단, timeout, 형식 오류 또는 이미지 URL 부재는 `status="deleted"`로 제공한다. 검색 자체가 실패해 Pin을 수집하지 못한 경우만 `PIN_SEARCH_UNAVAILABLE`로 분류한다.
- `pin_id`, `pin_url`, `status`는 세션·job 이력의 결과 필드로만 유지한다. `GET /api/jobs/{job_id}`는 저장된 `pin_id`로 widget을 다시 조회해 응답 전용 `thumbnail_url`을 조립한다. 별도 Pin 테이블·캐시·이미지 프록시를 만들지 않는다.
- `thumbnail_url`은 응답을 조립한 뒤 저장 전에 제거한다. 이미지 바이트·Pin 본문·작성자·보드·설명 등 widget의 나머지 응답 필드는 반환·저장·LLM 입력에 사용하지 않는다.

## AC

**AC-00 · Provider 계약과 fake 결과**

- GIVEN: 역할별 fake 결과에 `pin_id`, `pin_url`, `status`가 있는 `PinResult`가 주입됐다.
- WHEN: 같은 역할과 활성 카드 검색 조각으로 provider를 호출하고 결과를 조립한다.
- THEN: 해당 역할의 Pin 필드와 상태가 계약대로 전달되며 외부 호출은 없다.
- AND THEN: 반환 결과를 변경해도 다음 fake 호출의 결과는 변하지 않는다.

**AC-01 · Widget 기반 미리보기**

- GIVEN: 검색 provider가 Pin ID와 `pin_url`을 수집했다.
- WHEN: widget endpoint가 하나 이상의 이미지 URL을 반환한다.
- THEN: 가장 큰 이미지 URL을 응답 전용 `thumbnail_url`로 반환한다.
- AND THEN: 세션·job 이력에는 `pin_id`, `pin_url`, `status`만 남긴다.

**AC-02 · 이미지 URL 부재**

- GIVEN: 검색 provider가 Pin ID와 `pin_url`을 수집했다.
- WHEN: widget 응답에 이미지 URL이 없다.
- THEN: `thumbnail_url=null`, `status="deleted"`을 반환하고 UI는 접근할 수 없는 Pin으로 표시한다.

**AC-03 · 검색 장애**

- GIVEN: 공개 검색 요청이 일시적으로 실패한다.
- WHEN: 동일 job의 자동 재시도가 소진된다.
- THEN: 유효 카드가 있으면 `completed + partial_result`와 `PIN_SEARCH_UNAVAILABLE`을 반환한다.

**AC-04 · 외부 데이터 비저장**

- GIVEN: widget 응답이 이미지 URL과 추가 Pin 데이터를 포함한다.
- WHEN: API 응답과 세션·job 이력을 조립한다.
- THEN: `pin_id`, `pin_url`, `status`만 이력에 포함한다.
- AND THEN: `thumbnail_url`은 현재 API 응답에만 반환하고 저장·LLM 입력에 사용하지 않으며, 이미지 바이트와 Pin 본문·작성자·보드 정보는 저장·반환·LLM 입력에 사용하지 않는다.

**AC-05 · 프론트 응답의 이미지·Pin 링크**

- GIVEN: 검색 결과의 Pin URL이 검증되고 widget 응답에 이미지 URL이 있다.
- WHEN: 프론트가 완료된 job을 조회한다.
- THEN: 해당 `PinResult`에 응답 전용 `thumbnail_url`과 원본 `pin_url`을 함께 반환한다.
