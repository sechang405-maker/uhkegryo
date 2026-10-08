# LLM validation feedback retry

## Why

- 페르소나: 복합 조건을 입력하는 사용자.
- 문제: 역할 중복 출력이 거부돼도 같은 입력만 반복하여 수정 기회가 없다.
- 지표: 검증 실패 후 다음 attempt에 안전한 오류 피드백 전달율 100%.

## Goal

- 기존 최대 3회·backoff·lease 정책 안에서 검증 오류를 다음 호출에 전달한다.
- Out of Scope: 추가 호출·무제한 재시도, 원본 모델 출력 저장, 자동 중복 제거, 공개 API 변경.

## What

- 구조화 출력 검증 실패 시 오류 위치와 고정 오류 코드를 보관한다.
- 다음 worker가 Job을 claim하면 원래 요청과 함께 해당 오류를 전달하여 전체 JSON을 새로 생성한다.
- timeout·429에는 검증 피드백을 새로 생성하지 않는다. 종결 시 피드백을 비운다.
- resolver가 모든 후보를 거부하면 `invalid_candidate`로 다음 attempt를 요청한다.

## How

- migration은 `jobs.validation_feedback_json JSONB NULL`을 추가한다. 원본 출력·예외 메시지·잘못된 입력값은 저장하지 않는다.
- 새 worker 배포 전에 기존 `backend.db.migrate.migrate(connection)`으로 `004_validation_feedback.sql`을 적용한다. 기존 main의 `003_conversation_owners.sql` 이후 실행한다. 현재 앱 시작 시 자동 migration은 없으며, 누락된 컬럼에 대한 폴백은 제공하지 않는다.
- 피드백은 최대 8개 `{path,code}` 배열이다. path는 schema 필드명과 배열 index만 허용하고 알 수 없는 필드명은 `unknown_field`로 치환한다.
- JSON parse 오류는 `json_invalid`, 역할 중복은 `role_duplicate`, 순서는 `role_order`, 다른 root 검증 오류는 `state_rules`다. Pydantic field 오류는 `ValidationError.type`을 사용한다.
- 오류와 피드백 기록은 기존 attempt/status 조건을 가진 requeue UPDATE에서 함께 저장한다. stale worker는 기록하지 못한다.
- v1의 `interpret(..., validation_feedback=...)`는 오류 JSON을 별도 user message로 전달한다. v0의 모델 메시지는 유지한다. 이전 응답은 전달하지 않고 API 응답·일반 로그에 피드백을 추가하지 않는다.
- JSON 파싱·Pydantic 검증 실패에도 같은 worker trace 아래 generation을 한 번 기록한 뒤 기존 오류를 다시 전달한다. 실패 generation의 input/output은 `null`이고 metadata는 기존 job/session/attempt/max_attempts와 `error_type=pydantic_validation_error`, 최대 8개의 안전한 `validation_feedback={path,code}[]`만 포함한다. 모델·버전·usage는 기존 관측 필드를 사용하며 고정 ERROR 상태로 표시한다.
- 실패 generation에 원본 요청·모델 응답·입력값·예외 원문을 기록하지 않는다. Langfuse 키·현재 worker trace가 없으면 기록하지 않고 관측 장애도 원래 검증 오류와 retry 정책을 바꾸지 않는다.
- worker 재시작 후에도 DB의 피드백을 사용하며 완료·최종 실패·lease 소진 시 NULL로 정리한다.

## AC

- GIVEN 중복 pose 출력, WHEN 검증 실패 후 다음 attempt를 claim하면, THEN `role_duplicate` 피드백을 전달하고 기존 최대 3회를 유지한다.
- GIVEN 오류의 추가 필드명에 민감한 문자열, WHEN 피드백을 만들면, THEN 해당 문자열·입력값·예외 원문을 저장하거나 전달하지 않는다.
- GIVEN 다른 오류 또는 종결 상태, WHEN retry/complete 처리를 하면, THEN 이전 피드백을 비운다.
- GIVEN stale attempt, WHEN 피드백 기록을 시도하면, THEN 현재 Job의 피드백을 덮어쓰지 못한다.
- GIVEN 잘못된 JSON 또는 민감한 값·추가 필드명을 가진 Pydantic 실패 응답, WHEN adapter가 검증하면, THEN 같은 worker trace의 generation metadata에 안전한 오류 유형·attempt·최대 8개 오류만 남기고 input/output·로그에 원문을 남기지 않은 채 기존 오류를 전달한다.
