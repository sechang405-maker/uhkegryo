# Job trace 필수 필드 (작업 14)

## Why

- **페르소나**: 실패와 자동 재시도를 조사하는 운영자
- **상황**: 한 Job이 여러 worker attempt를 거쳐 완료되거나 실패한다.
- **문제**: LLM generation만으로는 단계, 재시도, 최종 상태를 같은 Job에서 추적할 수 없다.
- **측정 지표**: 관측이 활성화된 Job의 attempt 연결률 100%, 필수 필드 누락 0건, 금지 필드 기록 0건

## Goal

- 같은 `job_id`의 모든 attempt를 하나의 Langfuse trace ID로 연결한다.
- 각 attempt에 `job_id`, `session_id`, `attempt`, `max_attempts`, 모델, 프롬프트 버전과 처리 단계를 기록한다.
- 재시도 예약의 오류 유형·실제 backoff와 종결 상태를 안전한 코드로 기록한다.
- **Out of Scope**: Langfuse Prompt·Dataset 원격 등록, 비용·p50/p95 집계, Pinterest 검색 연결, API 응답 변경

## What

1. Worker가 Job을 claim하면 Job ID에서 결정론 trace ID를 만들고 attempt span을 연다.
2. `validating`, `searching`, `rendering` 단계별 span을 기록하고 LLM generation을 현재 trace의 자식으로 둔다. JSON·Pydantic 검증 실패 generation도 원문 없이 안전한 오류 metadata만 기록한다. 다른 실패한 LLM 호출은 attempt의 오류 필드로 기록한다.
3. 재시도 가능 오류는 `error_type`과 실제 `backoff_ms`를 남긴다. 최종 실패는 공개 `failure_code`를 남긴다.
4. 완료는 `agent_status`와 검색 사유 코드만 남긴다. 민감한 검색 결과 본문은 보내지 않는다.
5. Langfuse 키가 없으면 Job 처리를 그대로 수행하고 trace를 만들지 않는다.

**Edge Cases**: stale attempt 또는 lease 상실은 성공·실패로 기록하지 않는다. 관측 서버 장애는 Job 결과를 바꾸지 않는다. 재시도된 attempt는 새 trace가 아닌 같은 trace ID를 사용한다. worker 종료 시 마지막 attempt의 대기 중인 관측 이벤트를 전송한다.

## How

- `AgentJobWorker.run_once`가 claim한 Job의 `job_id`를 Langfuse `create_trace_id(seed=job_id)`에 전달한다. 각 attempt의 root observation은 `trace_context={"trace_id": trace_id}`를 사용한다.
- root observation 이름은 `agent-job-attempt`이며 입력은 `request_text`만 포함한다. `job_id`, `session_id`, `attempt`, `max_attempts`, `model`, `prompt_version`은 metadata에 문자열·정수로 기록한다.
- root가 열린 context 안에서 상태 전이 성공 시 해당 이름의 child span을 기록한다. LLM adapter의 generation은 동일 context의 자식이다.
- 재시도·종결 판정은 `JobRetryRecovery`의 동일한 정책 함수를 사용한다. retry attempt는 `failure_code=null`과 `backoff_ms=retry_delay_ms(...)`; 종결 실패는 `backoff_ms=null`과 API의 `FailureCode`를 기록한다.
- 완료 시 `agent_status`와 `reason_codes`만 기록한다. 일반 로그·trace에는 session cookie/token, API key, `anonymous_user_id`, Pin URL·thumbnail·본문, LLM 원본 응답을 추가하지 않는다. 사용자 요청 원문은 Langfuse root와 기존 LLM generation 입력에만 허용한다.
- Langfuse 키가 둘 다 설정된 경우에만 SDK client를 만든다. SDK 오류는 안전한 debug 로그로만 남기고 Job 상태 전이를 막지 않는다.
- `AgentJobWorker.run_forever`가 종료·취소되면 실행 중인 attempt observation을 닫은 뒤 소유한 Langfuse client의 `shutdown()`을 호출한다. 동기 `shutdown()`은 event loop를 막지 않도록 별도 thread에서 실행하고, 실패해도 worker 종료를 막지 않는다.

## AC

**AC-01 · 재시도 연결**
- GIVEN: 동일 Job이 timeout 두 번 뒤 세 번째 attempt에 성공한다.
- WHEN: worker가 각 attempt를 처리한다.
- THEN: 세 attempt의 trace ID가 같고 순서대로 attempt 1, 2, 3을 기록한다. 첫 두 attempt에는 `error_type=timeout`, `backoff_ms=1000`, `2000`, `failure_code=null`이고 마지막에는 성공 `agent_status`가 있다.

**AC-02 · 종결 실패**
- GIVEN: 설정 오류처럼 재시도하지 않는 오류 또는 세 번째 재시도 가능 오류가 있다.
- WHEN: Job이 failed로 종결된다.
- THEN: trace에는 공개 `failure_code`와 `backoff_ms=null`이 있고 내부 예외 원문은 없다.

**AC-03 · 민감 정보 경계**
- GIVEN: 요청에 session token과 Pin thumbnail URL이 있다.
- WHEN: Job 단계와 결과를 관측한다.
- THEN: trace 입력에는 요청 원문만 허용되고 metadata·output에는 token, thumbnail URL, secret, Pin 본문이 없다.

**AC-04 · 비활성화와 오류 격리**
- GIVEN: Langfuse 키가 없거나 관측 SDK가 실패한다.
- WHEN: worker가 Job을 처리한다.
- THEN: Job 상태·결과는 동일하며 관측 실패가 사용자 오류가 되지 않는다.

**AC-05 · 종료 시 전송**
- GIVEN: worker가 마지막 attempt observation을 닫았고 Langfuse client에 대기 중인 이벤트가 있다.
- WHEN: API 종료로 worker 루프가 취소된다.
- THEN: client의 `shutdown()`이 observation 종료 뒤 한 번 호출되며, 그 호출이 실패해도 worker 취소가 완료된다.
