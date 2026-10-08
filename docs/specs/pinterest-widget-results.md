# Pinterest Widget 결과 조립 (작업 12)

## Why

- **페르소나**: 그림 레퍼런스를 찾는 사용자.
- **상황**: 공개 검색은 원본 Pin ID·URL만 수집하며 저장된 Job에는 이미지 URL이 없다.
- **문제**: 미리보기를 제공하려면 Widget 조회가 필요하지만 이미지 URL을 Job 이력에 남겨서는 안 된다.
- **측정 지표**: 유효 이미지의 최대 면적 선택, 역할별 최대 8개와 원순서 보존, 저장 payload의 `thumbnail_url` 0건.

## Goal

- 수집된 Pin을 서버에서 Widget으로 조회해 응답 전용 `thumbnail_url`과 접근 상태를 만든다.
- 완료 Job 조회 시 저장된 Pin ID로 다시 조회해 미리보기를 현재 응답에만 넣는다.
- **범위 밖**: Worker의 검색 provider 연결·재시도 정책(작업 13), Pinterest API v5, 이미지 다운로드·프록시·캐시, 새로운 DB 컬럼.

## What

1. Widget `images`에서 유효한 HTTPS URL과 양의 정수 `width`·`height`를 가진 항목 중 면적이 가장 큰 URL을 선택한다. 면적이 같으면 원래 항목 순서를 따른다.
2. 이미지가 없거나 요청·HTTP·JSON·형식 오류가 나면 그 Pin을 `deleted`, `thumbnail_url=null`로 제공한다. 다른 Pin은 계속 처리한다.
3. 역할 결과의 처음 8개 Pin을 원순서대로 처리하며 Pin ID와 원본 URL을 유지한다. 검색 자체의 `PIN_RESULTS_EMPTY`·`PIN_SEARCH_UNAVAILABLE` 코드는 변경하지 않는다.
4. `GET /api/jobs/{job_id}`는 세션 소유권 검증과 Job 조회를 마친 뒤, 완료 결과에 있는 Pin만 Widget으로 다시 조회한다. 진행·실패·Pin 없는 완료 결과에는 Widget 호출을 하지 않는다.
5. Widget 응답의 이미지 URL 이외 필드와 이미지 바이트는 저장·로그·trace·LLM 입력에 쓰지 않는다. 저장된 Job 객체도 변경하지 않는다.

## How

- `PinterestWidgetClient`는 `https://widgets.pinterest.com/v3/pidgets/pins/info/?pin_ids={pin_id}`에 서버 측 GET 요청을 보내며 타임아웃은 10초다. Pin ID는 숫자 문자열만 허용한다. 기본 HTTP 구현은 `httpx.AsyncClient`; 테스트에서는 비동기 JSON loader를 주입한다.
- 응답 형식은 `data`의 Pin 목록에서 요청 ID와 일치하는 항목의 `images` mapping이다. ID 불일치·누락은 이미지 없음으로 처리한다.
- `PinterestWidgetProvider`는 기존 `PinterestProvider.search` 결과를 `enrich_outcome(RoleSearchOutcome)`으로 보강해 같은 provider 계약을 제공한다. `enrich_job(JobEnvelope)`은 새 완료 응답을 만든다. 두 함수는 Widget client를 공유하며 입력 객체를 변경하지 않는다.
- `GET /api/jobs/{job_id}`는 기존 repository 조회 뒤 `enrich_job`을 호출한다. Widget 조회는 동시에 최대 8건으로 제한한다.
- `JobRepository._dump`의 기존 `thumbnail_url` 제거 계약을 유지한다. Widget 정보는 이 경계 이전에 저장하지 않는다.

## AC

**AC-01 · 큰 이미지와 원순서**
- GIVEN: 두 Pin의 Widget `images`에 서로 다른 면적의 유효 이미지가 있다.
- WHEN: 역할 결과를 보강한다.
- THEN: 각 Pin의 최대 면적 URL을 고르고 원래 Pin 순서·ID·URL을 유지하며 8개까지만 반환한다.

**AC-02 · 접근 불가와 격리**
- GIVEN: 한 Pin의 Widget이 이미지 없음·HTTP 오류·형식 오류 중 하나를 반환한다.
- WHEN: 역할 결과를 보강한다.
- THEN: 해당 Pin만 `deleted`·`thumbnail_url=null`이고 나머지 Pin은 정상 결과를 유지한다.

**AC-03 · 응답 전용 조회**
- GIVEN: 저장된 완료 Job 결과에 `thumbnail_url` 없는 Pin이 있다.
- WHEN: 소유 세션이 `GET /api/jobs/{job_id}`를 두 번 호출한다.
- THEN: 매번 Widget을 조회한 URL은 해당 응답에만 포함되고 저장된 Job과 저장 payload에는 없다.
- AND THEN: 진행·실패 Job이나 권한 없는 조회는 Widget을 호출하지 않는다.

**AC-04 · 외부 데이터 최소화**
- GIVEN: Widget 응답에 이미지 이외 Pin 본문·작성자·보드 필드가 있다.
- WHEN: 결과를 조립한다.
- THEN: 허용된 `pin_id`, `pin_url`, `status`, 응답 전용 `thumbnail_url`만 반환한다.
