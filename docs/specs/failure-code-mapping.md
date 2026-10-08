# 실패 코드와 사용자 메시지 매핑 (작업 15)

## Why

- **페르소나**: 비동기 Agent 요청을 제출한 사용자와 장애를 확인하는 운영자.
- **상황**: LLM 오류는 분류되지만 DB·설정·Worker 오류가 내부 코드 오류로 섞인다.
- **문제**: 운영자가 원인을 구분하기 어렵고 예외 원문에는 Secret이나 연결 정보가 포함될 수 있다.
- **측정 지표**: 지원 예외의 공개 코드 일치율 100%, 실패 payload·trace 오류 출력의 비밀값 노출 0건.

## Goal

- 오류 발생 경계와 예외 타입으로 공개 `FailureCode`를 결정한다.
- API·Job 실패 payload·trace의 실패 코드를 일치시키고 고정 한국어 안내를 사용한다.
- **범위 밖**: 새 FailureCode, DB 복구·재접속 정책 변경, LLM 재시도 횟수 변경, UI·평가 기능.

## What

1. 분류된 LLM 오류는 기존 코드를 유지한다. OpenRouter HTTP 401·403은 재시도하지 않는 `CONFIGURATION_ERROR`다.
2. DB 인증·잘못된 database 설정은 `CONFIGURATION_ERROR`, 연결 장애는 `DATABASE_UNAVAILABLE`, 누락된 table·column·schema 또는 migration 실행 실패는 `DATABASE_MIGRATION_ERROR`다.
3. 카탈로그 검증 실패는 `CATALOG_INVALID_AT_STARTUP`, 예기치 않은 코드 예외는 `INTERNAL_CODE_ERROR`다. 만료 lease의 `JOB_INSTANCE_INTERRUPTED` 계약을 유지한다.
4. 검색 loader 경계의 timeout은 `SEARCH_TIMEOUT`, HTTP 429는 `SEARCH_RATE_LIMITED`, 나머지 loader 접근 장애는 `SEARCH_UPSTREAM_UNAVAILABLE`로 운영 로그에 기록한다. 검색 실행 의존성 누락은 `CONFIGURATION_ERROR`다.
5. 검색 장애는 작업 13의 역할 재시도·`PIN_SEARCH_UNAVAILABLE` 부분 결과를 유지한다. Widget의 Pin별 `deleted` 계약을 바꾸지 않는다.
6. 모든 종결 `Failure`의 `user_message`는 “현재 요청을 처리하지 못했습니다. 잠시 후 새 메시지로 다시 시도해 주세요.”이며 `retryable=false`다. 예외 원문·HTTP 헤더·SQL·Secret은 공개 payload 또는 trace 오류 출력에 넣지 않는다.
7. DB가 끊겨 실패 상태 저장도 불가능하면 성공적으로 종결했다고 간주하지 않는다. trace는 분류된 장애를 기록하고 기존 lease 복구를 따른다.

## How

- `backend/services/failure_mapping.py`를 단일 분류 경계로 사용한다. 임의 예외의 `failure_code` 속성이나 메시지 문자열을 신뢰하지 않는다.
- `LLMError`와 명시적인 운영 오류 wrapper의 enum 코드, `CatalogLoadError`, asyncpg의 인증·스키마·연결 예외 타입을 분류한다. 일반 `OSError`·`TimeoutError`는 DB 호출 경계에서만 DB 장애다.
- 접속 준비 전 `asyncpg.CannotConnectNowError`와 연결 포화 `asyncpg.TooManyConnectionsError`도 `DATABASE_UNAVAILABLE`이다. API는 HTTP 503과 고정 안내를 반환하고 Worker heartbeat·실패 저장 경계는 같은 코드로 trace한다.
- SearXNG HTTP loader 경계는 httpx timeout과 HTTP 상태로 분류한다. 오류 원문을 로그에 넣지 않고 `failure_code`만 기록한다.
- migration wrapper는 transaction rollback 이후 `DATABASE_MIGRATION_ERROR` 운영 오류를 전달한다. 연결·인증 오류는 해당 분류를 유지한다.
- `JobRetryRecovery`와 `AttemptTrace.failed`는 같은 분류 함수를 쓴다. 기존 LLM 재시도 정책을 유지하고 DB·설정·코드 오류를 자동 재시도하지 않는다.
- `/api` 예외 응답은 알려진 DB·설정 장애에 HTTP 503, 예상하지 않은 코드 오류에 HTTP 500과 동일한 세 필드 `Failure`를 반환한다. 기존 401·404·409·422 요청 오류 계약은 유지한다.

## AC

**AC-01 · 예외 분류**
- GIVEN: LLM·DB 연결·인증·스키마·migration·카탈로그·알 수 없는 코드 예외가 있다.
- WHEN: 오류를 분류한다.
- THEN: 명시된 FailureCode를 반환하고 예외 메시지는 결과에 포함하지 않는다.

**AC-02 · API와 저장·trace 비노출**
- GIVEN: 예외 원문에 Secret과 DB 연결 문자열이 있다.
- WHEN: API 응답 또는 Worker 실패 payload와 trace 오류 출력을 만든다.
- THEN: 고정 안내 문구와 동일한 분류 코드만 포함하고 비밀값은 없으며 `retryable=false`다.

**AC-03 · 인증·migration 결정 오류**
- GIVEN: OpenRouter 401·403 또는 migration SQL 오류가 발생한다.
- WHEN: 해당 호출 경계가 예외를 처리한다.
- THEN: 각각 CONFIGURATION_ERROR 또는 DATABASE_MIGRATION_ERROR로 분류하고 자동 재시도하지 않는다.

**AC-04 · 검색 부분 결과 유지**
- GIVEN: 검색 loader가 timeout·429·접근 장애를 반환한다.
- WHEN: 공개 검색 provider가 오류를 처리한다.
- THEN: 해당 SEARCH 코드를 비밀값 없이 기록하고 결과는 PIN_SEARCH_UNAVAILABLE이다.

**AC-05 · DB 접속 준비·연결 포화**
- GIVEN: DB 호출에서 CannotConnectNowError 또는 TooManyConnectionsError가 발생한다.
- WHEN: API 요청 또는 Worker heartbeat가 해당 오류를 처리한다.
- THEN: API는 DATABASE_UNAVAILABLE·고정 안내·retryable=false와 HTTP 503을 반환하고 Worker trace도 DATABASE_UNAVAILABLE이며 예외 원문을 노출하지 않는다.
