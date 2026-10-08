# Session Repository

## Why

- **페르소나**: 익명 브라우저 사용자의 세션을 처리하는 API 서버
- **상황**: 서버 재시작 후에도 세션 식별 및 활동 갱신이 유지되어야 한다.
- **문제**: 프로세스 메모리 저장은 재시작 시 세션을 잃고, 토큰 원문을 DB에 둘 위험이 있다.
- **측정 지표**: 생성된 세션의 DB 재조회 성공률 100%, 토큰 원문 저장 0건, 만료 정리 완료.

## Goal

- `asyncpg` 기반 PostgreSQL repository에 익명 소유자의 토큰 SHA-256 hash와 소유 대화 UUID를 분리 저장한다.
- hash로 기본 대화를 조회하고, 대화 열기·접수 시에만 활동을 갱신한다.
- 마지막 활동으로부터 3개월을 초과한 세션을 삭제하고 삭제 건수를 반환한다.
- **Out of Scope**: job 저장소/worker, API 라우터의 인메모리 저장소 교체, 자동 스케줄러, DB pool 앱 수명주기.

## What

**Happy Path**
1. 호출자가 세션 token을 생성하고 repository에 전달한다.
2. repository는 token hash만 저장하고 새 `session_id`를 반환한다.
3. 이후 같은 token으로 조회하면 미만료 기본 대화의 `session_id`를 반환하며 조회만으로 활동 시간을 갱신하지 않는다.
4. 정리 작업은 3개월 넘게 활동이 없는 세션을 삭제하고 삭제 수를 돌려준다.

**Edge Cases**

| # | 상황 | 처리 방식 |
|---|---|---|
| EC-01 | token이 빈 값 | 세션을 만들지 않고 `ValueError` |
| EC-02 | 동일 token hash 중복 | 같은 익명 소유자를 재사용하고 새 대화를 추가함 |
| EC-03 | 미등록 token 조회 | `None` 반환, 행을 만들지 않음 |
| EC-04 | 활동 갱신과 만료 정리가 동시 실행 | DB 시각 기준으로 만료 조건을 평가하고 삭제 결과는 실제 삭제 행 수 |
| EC-05 | DB 오류 | 예외를 호출자에게 전달, 성공으로 가장하지 않음 |

## How

- `SessionRepository(pool)`은 `asyncpg.Pool`을 받는다.
- `create_session(token: str) -> str`은 `session_id` UUID 문자열을 반환한다. `created_at`과 `last_activity_at`은 DB의 `now()`로 초기화한다.
- `resolve_session(token: str) -> str | None`은 입력을 `backend.shared.auth.hash_session_token`으로 hash하고, 소유자의 미만료 기본 대화 `session_id`를 반환하고 활동 시각은 바꾸지 않는다.
- `delete_expired_sessions() -> int`은 `last_activity_at + interval '3 months' <= now()`인 행을 삭제하고 삭제 수를 반환한다.
- migration과 다중 대화 API의 현재 계약은 [conversation-sessions.md](conversation-sessions.md)를 따른다. 003 migration은 기존 cookie/hash·session UUID·job을 보존한다.
- 원문 token은 SQL 인자로 hash 계산 전후를 제외한 영속 데이터에 저장하지 않는다. 애플리케이션 로그를 추가하지 않는다.
- 정리 스케줄 실행은 운영 호출자가 담당한다.

## AC (Given-When-Then)

- **AC-01 · 세션 생성**: GIVEN 유효한 opaque token, WHEN repository가 세션을 생성, THEN UUID `session_id`와 hash만 저장된 행이 생성된다.
- **AC-02 · hash 조회와 활동 분리**: GIVEN 저장된 token, WHEN repository가 token으로 세션을 조회, THEN 같은 기본 `session_id`를 반환하고 DB `last_activity_at`은 변경하지 않는다.
- **AC-03 · 미등록 token**: GIVEN 저장되지 않은 token, WHEN 조회, THEN `None`을 반환하고 세션 행을 만들지 않는다.
- **AC-04 · 만료 정리**: GIVEN 3개월 초과 비활성 세션과 최근 활동 세션, WHEN 정리를 실행, THEN 오래된 행만 삭제하고 삭제 행 수를 반환한다.
- **AC-05 · 입력 검증**: GIVEN 빈 token, WHEN 세션 생성 또는 조회, THEN DB 호출 전에 `ValueError`가 발생한다.
