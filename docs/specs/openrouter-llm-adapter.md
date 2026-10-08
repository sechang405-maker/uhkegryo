# OpenRouter LLM Adapter

## Why

Agent는 provider별 코드 변경 없이 model을 교체하면서도, 허용된 term 후보만 구조화 출력으로 받아야 한다.

## Goal

- OpenRouter를 단일 LLM provider로 사용한다.
- 배포 환경의 `LLM_MODEL`만 바꿔 model을 교체한다.
- 180초 안에 계약된 구조화 출력만 worker에 반환한다.

## What

adapter 입력은 사용자 원문과 활성 TERM_CARD 후보 경계다. 현재 출력은 `InterpretationOutput={interpretation_state, clarification_type, selections, unresolved_constraints, clarifying_question}`이며 각 selection은 `{role, term_id, evidence, confidence}`다. `needs_clarification`일 때 `clarification_type`은 `abstract_intent | insufficient_visual_evidence | conflicting_constraints` 중 하나이고, resolver만 이를 최종 reason code로 검증·변환한다. adapter는 검색 URL·Pin·최종 Agent 상태를 만들지 않는다. 선택지 후보 출력은 [선택형 후속 질문 Spec](./clarification-choices.md)의 후속 구현 전까지 비활성이다.

## How

- `OPENROUTER_API_KEY`, `OPENROUTER_BASE_URL`, `LLM_MODEL`은 환경 변수로 읽고 코드에는 model명을 하드코딩하지 않는다.
- 호출 timeout은 180초다. OpenRouter SDK의 내부 재시도는 `max_retries=0`으로 끈다. job worker만 attempt·backoff·최종 실패를 결정하므로 SDK 재시도를 유지하면 최대 3회 계약보다 더 많은 호출이 발생하고 관측 attempt와 실제 호출 수가 달라진다.
- 아래 표는 LLM 실행 재시도의 단일 기준이다. 최초 실행을 포함해 최대 3회이며, 1·2번째 실패 뒤에만 다음 job attempt를 예약한다. `backoff_ms`는 실제 예약값을 기록한다.

| 오류 분류 (`error_type`) | 최초 실행 뒤 추가 시도 | 다음 시도 전략 | backoff | 세 번째 실패의 `failure_code` | 사용자 응답 |
| --- | --- | --- | --- | --- | --- |
| `pydantic_validation_error` | 2회 | 검증 오류를 포함해 계약된 `InterpretationOutput`만 다시 생성하도록 구조화 출력 재요청 | 1차 실패 뒤 1,000ms, 2차 실패 뒤 2,000ms | `LLM_INVALID_STRUCTURED_OUTPUT` | 일반 실패 문구 |
| `timeout` | 2회 | 같은 입력·모델로 새 요청 | 1차 실패 뒤 1,000ms, 2차 실패 뒤 2,000ms | `LLM_TIMEOUT` | 일반 실패 문구 |
| `upstream_5xx` | 2회 | 같은 입력·모델로 새 요청 | 1차 실패 뒤 1,000ms, 2차 실패 뒤 2,000ms | `LLM_UPSTREAM_UNAVAILABLE` | 일반 실패 문구 |
| `rate_limited` (429) | 2회 | 같은 입력·모델로 새 요청 | 유효한 `Retry-After`를 밀리초로 변환해 `min(max(value, 1,000), 30,000)`; 없거나 해석 불가하면 1,000ms·2,000ms | `LLM_RATE_LIMITED` | 일반 실패 문구 |
| `incomplete_or_unclassified_upstream` | 2회 | 미완료 응답 또는 SDK·네트워크에서 온 분류 불가 upstream 예외를 같은 입력·모델로 새 요청 | 1차 실패 뒤 1,000ms, 2차 실패 뒤 2,000ms | `LLM_UPSTREAM_UNAVAILABLE` | 일반 실패 문구 |

- Adapter 예외는 worker가 기록할 `error_type`을 제공한다. timeout은 `timeout`, 429는 `rate_limited`, HTTP 5xx는 `upstream_5xx`, 미완료 응답·분류 불가 upstream 오류는 `incomplete_or_unclassified_upstream`, Pydantic 출력 검증 오류는 `pydantic_validation_error`다.
- `Retry-After`는 delay-seconds와 HTTP-date 형식을 모두 받는다. HTTP-date는 현재 UTC 시각까지의 delay로 변환하고 1,000~30,000ms로 clamp한다. 이미 지난 날짜나 해석할 수 없는 값은 유효하지 않은 값으로 보고 worker의 attempt별 기본 backoff(1,000ms·2,000ms)를 사용한다.
- 우리 코드가 던진 예외는 `incomplete_or_unclassified_upstream`으로 바꾸지 않는다. `INTERNAL_CODE_ERROR`로 즉시 failed 처리하며 자동 재시도하지 않는다.
- OpenRouter HTTP 401·403은 `error_type=configuration`, `CONFIGURATION_ERROR`로 즉시 실패하며 자동 재시도하지 않는다. 예외 원문과 인증 응답 본문은 공개 오류에 포함하지 않는다.
- API 키는 trace·로그에 기록하지 않는다. 사용자 원문은 Langfuse trace에만 기록하며 LLM 원본 응답은 저장하지 않는다.
- resolver가 adapter 출력을 JSON 카탈로그와 대조해 활성 term·역할·조건을 검증한다.
- [v1 출력 구조 전달](./interpreter-json-shape.md)은 해석 프롬프트와 출력 Skill을 결합한다. 활성화 시 Prompt 경로와 버전을 함께 v1으로 지정하며 v0의 프롬프트·JSON mode는 유지한다.
- [출력 Skill](./structured-output-skill.md)은 v1 해석 프롬프트 뒤에 출력 규칙을 한 번 결합한다. v1 해석 호출에만 코드 유래 `json_schema`와 `provider.require_parameters=true`를 전달하며, [검증 피드백](./llm-validation-feedback.md)은 기존 Job attempt 사이의 안전한 오류 위치·코드와 원문 없는 실패 generation을 정의한다.

## AC

- GIVEN: `LLM_MODEL` 값 변경, WHEN: adapter를 재시작, THEN: 코드 변경 없이 새 model로 요청한다.
- GIVEN: 180초 timeout, WHEN: worker가 처리, THEN: 첫 실패 뒤 `next_retry_at`은 1,000ms 후이며 해당 attempt는 `LLM_TIMEOUT`으로 회복 처리한다.
- GIVEN: 계약 밖 term ID가 포함된 구조화 출력, WHEN: resolver가 검증, THEN: 검증 오류를 포함한 구조화 출력 재요청을 최대 두 번 더 하고 세 번째도 실패하면 `LLM_INVALID_STRUCTURED_OUTPUT`으로 처리한다.
- GIVEN: OpenRouter가 `Retry-After: 60`과 429를 반환, WHEN: worker가 다음 시도를 예약, THEN: SDK 내부 재시도 없이 `error_type=rate_limited`, `backoff_ms=30,000`, `failure_code=null`을 기록한다.
- GIVEN: OpenRouter가 미래 HTTP-date 형식 `Retry-After`를 반환, WHEN: adapter가 delay를 변환, THEN: 현재 시각과의 차이를 millisecond로 바꾸고 1,000~30,000ms 범위로 clamp한다.
- GIVEN: OpenRouter가 이미 지난 HTTP-date `Retry-After`를 반환, WHEN: adapter가 delay를 변환, THEN: `retry_after_ms=null`을 worker에 전달해 attempt 기본 backoff를 사용하게 한다.
- GIVEN: LLM 호출이 timeout, 429, HTTP 5xx, 미완료 응답 또는 Pydantic 검증 실패로 끝남, WHEN: adapter가 예외를 worker에 전달, THEN: 각각 `timeout`, `rate_limited`, `upstream_5xx`, `incomplete_or_unclassified_upstream`, `pydantic_validation_error`를 제공한다.
- GIVEN: 정상 구조화 출력, WHEN: resolver가 처리, THEN: adapter는 최종 상태나 검색 URL을 결정하지 않는다.

## 대화 기억 변경

대화 기억 확장: interpret는 서버 session_context를 받는다. memory(classify/summarize/answer)는 같은 client/model/timeout/오류 매핑을 재사용하고 별도 구조화 출력 모델을 검증한다. 요청 재시도는 기존 worker attempt만 담당한다. 원격 Prompt/production label은 자동 변경하지 않는다.
