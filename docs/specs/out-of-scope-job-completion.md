# 범위 밖 요청의 job 종결 저장

## Why
- 페르소나: 미지원 작업을 요청한 사용자와 실제 worker를 평가하는 개발자.
- 상황: worker는 VALIDATING 단계에서 범위 밖 입력을 판정하지만 저장 계층은 이 단계의 COMPLETED 전환을 unsafe_input에만 허용한다.
- 문제: 모델 호출 없이 종료할 요청이 INTERNAL_CODE_ERROR로 실패한다. 전체 평가 EVAL-17~20 네 건에서 재현됐다.
- 지표: 네 건의 completed/out_of_scope 종결, LLM·검색 호출 0건.

## Goal
- 범위 밖 server gate의 정상 응답을 VALIDATING에서 COMPLETED로 저장한다.
- 기존 unsafe gate·일반 결과의 상태 전환 제한을 유지한다.
- 제외: 범위 판정 규칙, API schema, 일반 job 전이, 모델·검색 provider 변경.

## What
- 안전 검사를 먼저 수행하고, 범위 밖 요청은 out_of_scope와 OUT_OF_SCOPE_REQUEST로 완료한다.
- 이 gate는 memory/LLM·검색·rendering 단계에 진입하지 않는다.
- VALIDATING의 success/partial_result/needs_clarification 완료 전환은 여전히 거부한다.

## How
- JobRepository.update_status의 조기 COMPLETED 전환 허용 상태에 OUT_OF_SCOPE를 UNSAFE_INPUT과 함께 추가한다.
- PostgreSQL migration 및 DB schema 변경은 없다. attempt·이전 status 조건과 원래 job 전이 검증을 유지한다.
- 실제 PostgreSQL로 EVAL-17~20의 execute 경로를 평가하며 adapter가 호출되면 테스트가 실패하도록 한다.
- JobRepository의 SQL 조건을 검증하는 회귀 테스트에서 두 gate만 VALIDATING 완료를 허용함을 확인한다.

## AC
- Given 긍정적인 미지원 작업 EVAL-17~20, When 실제 worker 실행, Then completed/out_of_scope와 OUT_OF_SCOPE_REQUEST이며 LLM·검색 호출이 없다.
- Given unsafe_input, When VALIDATING 종결, Then 기존 completed/unsafe_input 동작을 유지한다.
- Given 일반 success, When VALIDATING에서 곧바로 COMPLETED 전환, Then 저장을 거부한다.

검증(2026-10-02): 실제 PostgreSQL worker 평가 EVAL-17~20 전부 out_of_scope 정상 완료, 모델·검색 호출 0건. 두 조기 gate 허용과 일반 success 거부 회귀 테스트 통과. [검증 문서](../../evals/ambiguity-quality-review-2026-10-02.md).
