# 출력 검증 실패 진단 보존

## Why
최종 실패 시 validation_feedback_json이 지워져 JSON 오류와 대화 근거 오류를 구분할 수 없다.

## Goal
최종 검증 실패의 단계·필드 경로·고정 오류 코드를 내부 DB에 보존한다. 사용자 응답, 재시도 정책, 출력 스키마는 변경하지 않는다.

재시도 가능한 실패도 attempt별로 보존하여 이후 성공하거나 다른 오류로 종료해도 원인을 조회할 수 있게 한다. Langfuse의 해당 attempt에도 동일한 안전한 진단을 기록한다. 기존 삭제 기록 복원, 공개 진단 API, 배포는 범위 밖이다.

## What
검증 오류 종료 시 진단 목록을 저장한다. 다른 오류 종료 시 이전 진단은 지운다. 원문, 모델 출력, 예외 메시지, 키는 저장하지 않는다.

재시도용 진단과 별도로 검증 실패 이력을 누적한다. 성공·비검증 실패·lease 복구 시 이력은 유지한다. stale attempt는 이력을 쓰지 않으며, 동일 attempt의 중복 실패 처리는 기존 상태 조건으로 차단한다.

## How
기존 validation_feedback_json 컬럼을 사용한다. 단계는 interpretation_schema, memory_schema, conversation_validation이다. 최대 8개 항목과 허용된 스키마 필드/오류 코드만 저장한다. 알 수 없는 값은 고정 대체값으로 치환한다. 재시도용 feedback 구조는 유지한다. 기존 실패의 삭제된 기록은 복원할 수 없다.

- migration 005로 jobs.validation_failure_history_json JSONB NOT NULL DEFAULT '{}'를 추가한다.
- 이력은 attempt 번호를 키로 하고 값은 `{stage, path, code}` 목록이다. 예: `{"1":[{"stage":"conversation_validation","path":[],"code":"selection_evidence_invalid"}]}`.
- 실패 상태 전환 UPDATE와 같은 쿼리에서 안전한 진단을 해당 attempt 키에 기록한다. 기존 attempt/max_attempts/상태 조건을 그대로 적용한다. 비검증 오류는 이력을 변경하지 않는다.
- Langfuse agent-job-attempt의 metadata.validation_diagnostics에 동일 목록을 남긴다. metadata.attempt와 함께 원인을 조회한다. 전송 실패는 Job 처리에 영향을 주지 않는다.
- 운영자는 DB에서 `SELECT validation_failure_history_json FROM jobs WHERE job_id = ...` 또는 Langfuse의 해당 attempt Attributes에서 조회한다. Job 삭제 시 DB 이력도 함께 삭제된다.

## AC
- Given 검증 오류, When 최종 시도가 실패하면, Then 단계·경로·코드를 보존한다.
- Given role_duplicate 검증 오류로 마지막 attempt가 실패, When PostgreSQL 종결 상태를 조회, Then status=failed이며 validation_feedback_json에 interpretation_schema 단계·빈 path·role_duplicate 코드가 있고 해당 attempt의 validation_failure_history_json에도 동일 진단이 남는다.
- Given 원문을 담은 임의 진단값, When 저장하면, Then 원문은 고정 대체값으로 치환된다.
- Given 비검증 오류, When 최종 실패하면, Then 진단값은 null이고 공개 실패 계약은 동일하다.
- Given 대화 근거 불일치, When 검증하면, Then 고정 원인 코드와 conversation_validation 단계가 발생한다.
- Given attempt 1 검증 실패 후 attempt 2 성공, When 완료되면, Then 재시도 feedback은 지워져도 attempt 1 이력은 유지된다.
- Given 서로 다른 두 attempt 검증 실패, When 저장하면, Then 각 attempt의 진단이 독립된 키에 보존된다.
- Given 비검증 실패 또는 lease 복구, When 상태가 변경되면, Then 기존 이력을 변경하지 않는다.
- Given stale attempt 실패, When 조건부 UPDATE가 거부되면, Then 이력도 변경되지 않는다.
- Given 원문을 포함한 진단값, When 재시도 이력과 Langfuse를 기록하면, Then 허용된 단계·경로·코드만 남는다.

## 검증 경계
모의 DB 테스트 및 관련 회귀 테스트로 확인한다. 실제 유료 LLM 요청과 Neon 쓰기 테스트는 별도 승인 없이는 실행하지 않는다.

검증(2026-10-07): 현재 계약에 맞춘 두 PostgreSQL 통합 테스트와 진단 보존 관련 테스트 15개 통과. 기존 로컬 Langfuse 변경을 제외한 PR 작업 폴더에 동일 테스트 수정을 적용해 전체 backend 636개 통과(실제 임시 PostgreSQL 16, LLM·검색 fixture).
