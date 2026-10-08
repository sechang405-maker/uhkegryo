# 관측과 프롬프트 버전 규칙

## Why

비동기 job의 자동 재시도·부분 결과·최종 실패를 안전하게 운영하려면 요청 단위로 상태와 시도 횟수를 추적해야 한다.

## Goal

- LLM 해석 프롬프트와 job 처리 경로를 안전한 trace 필드로 추적한다.
- 자동 재시도와 최종 failure code를 운영자가 구분할 수 있게 한다.
- Prompt 버전·모델·비용·지연과 30건 평가셋 품질을 같은 기준으로 비교한다.

## What

기본 해석 프롬프트 이름은 `uhkegryo-interpreter-v{n}`이고 production label을 사용한다. 모델 또는 프롬프트 변경 시 버전을 증가시킨다. `prompts/uhkegryo-interpreter-v0.md`는 v0의 저장소 검토 원본이며, 원격 Langfuse Prompt 등록 전후에 내용과 버전을 대조한다.

각 Langfuse trace에는 사용자 요청 원문, `job_id` UUID 원문, `session_id` UUID 원문, 모델, `prompt_version`, `attempt`, `max_attempts`, 단계, `error_type`, 실제 적용한 `backoff_ms`, 최종 `agent_status`, `failure_code`, 검색 결과 상태를 기록한다. `job_id`와 `session_id`는 trace 식별·세션 그룹화를 위한 운영 필드다. 일반 애플리케이션 로그에는 요청 원문 대신 해시·길이·선택된 term ID만 기록하며, LLM 원본 응답은 저장하지 않는다. 세션 쿠키 토큰 원문·해시, API key, `anonymous_user_id` 원문은 기록하지 않는다.

## How

- 자동 실행 재시도는 같은 job의 `attempt=1..3`으로 기록한다. 사용자에게 재시도 진행을 표시하지 않는다.
- Langfuse trace는 job마다 하나만 만든다. attempt와 validating·searching·rendering 같은 처리 단계는 같은 trace 안의 observation 또는 span으로 기록하고, worker가 job 종결 시 trace를 종료한다. LLM adapter는 worker가 전달한 관측 context에 LLM 호출 observation을 추가한다.
- `LLM_*`, `SEARCH_*`, `JOB_INSTANCE_INTERRUPTED`은 각 시도의 안전한 오류 분류와 지연을 기록한다. LLM `error_type`은 `pydantic_validation_error`, `timeout`, `upstream_5xx`, `rate_limited`, `incomplete_or_unclassified_upstream` 중 하나이며, 오류별 backoff와 최종 포기 경로는 [openrouter-llm-adapter.md](./openrouter-llm-adapter.md)를 따른다.
- 재시도를 예약한 attempt 1·2는 `error_type`과 실제 양수 `backoff_ms`를 기록하고 `failure_code=null`이다. 종결 attempt는 `error_type`과 최종 `failure_code`를 기록하고 다음 재시도가 없으므로 `backoff_ms=null`이다. 성공 attempt는 `error_type=null`, `backoff_ms=null`, `failure_code=null`이다.
- 최종 `failed`에는 API와 같은 안정된 failure code를 기록한다. 운영 로그에는 안전한 오류 요약을 추가할 수 있으나 UI에 노출하지 않는다.
- 검색 재시도 소진 뒤 유효 카드가 있으면 `completed + partial_result`, `PIN_SEARCH_UNAVAILABLE`을 기록한다.
- `needs_clarification`은 실패가 아니며 새 사용자 메시지의 새 job과 연결한다.
- API 키, 세션 토큰, `anonymous_user_id` 원문, 이미지 바이트, 썸네일 URL, Pin 본문 등 부가 메타데이터는 기록하지 않는다. 사용자 요청 원문은 Langfuse trace에만 기록한다.
- Langfuse Prompt 원격 버전은 `uhkegryo-interpreter-v{n}` 이름과 version label로 관리한다. `production` label은 30건 baseline과 회귀 확인 전에는 바꾸지 않는다.

Worker의 Job trace 필수 필드와 수명주기 구현 범위는 [job-trace-required-fields.md](./job-trace-required-fields.md)를 따른다. 원격 Prompt 등록·Dataset 연결과 평가 집계는 별도 작업이다.

## AC

**AC-01 · 자동 재시도 관측**

- GIVEN: LLM timeout이 두 번 발생하고 세 번째 시도가 성공한다.
- WHEN: job을 종료한다.
- THEN: 같은 job ID의 attempt 1, 2, 3과 최종 성공 상태를 기록한다.
- AND THEN: attempt 1·2에는 `error_type=timeout`, 각각 `backoff_ms=1000`, `2000`을 기록한다.

**AC-02 · 최종 실패 관측**

- GIVEN: 결정적 설정 오류가 발생한다.
- WHEN: job을 종료한다.
- THEN: failure code와 안전한 운영 요약을 기록하고 사용자 UI에는 내부 정보를 전달하지 않는다.

**AC-03 · 오류별 backoff·최종 포기**

- GIVEN: Pydantic 검증 오류, timeout, 5xx, 429 또는 미완료·분류 불가 upstream 예외가 세 번 연속 발생한다.
- WHEN: 세 번째 attempt를 종료한다.
- THEN: attempt 1·2는 해당 `error_type`, 실제 양수 `backoff_ms`, `failure_code=null`을 기록한다.
- AND THEN: 세 번째 trace는 각각 `LLM_INVALID_STRUCTURED_OUTPUT`, `LLM_TIMEOUT`, `LLM_UPSTREAM_UNAVAILABLE`, `LLM_RATE_LIMITED`, `LLM_UPSTREAM_UNAVAILABLE` 최종 failure code와 `backoff_ms=null`을 기록한다.
- AND THEN: API는 failure code를 반환하고 UI는 일반 실패 문구만 표시한다.

**AC-04 · 429 상한**

- GIVEN: OpenRouter가 `Retry-After: 60`과 429를 반환한다.
- WHEN: 다음 attempt를 예약한다.
- THEN: trace의 `error_type=rate_limited`, `backoff_ms=30000`이며 worker는 `next_retry_at` 전에는 job을 claim하지 않는다.

**AC-05 · Prompt 버전·비용·지연 연결**

- GIVEN: 동일한 30건 평가셋으로 baseline 또는 변경 후 실행을 한다.
- WHEN: 각 LLM 호출과 평가 실행을 기록한다.
- THEN: 모델 provider·name, `prompt_version`, token 수, 요청당 비용, 단계별 지연과 p50/p95를 같은 실행 기록에서 비교할 수 있다.

Generation 실제 호출 구간과 표준 session_id 전파는 [langfuse-generation-session-repair.md](langfuse-generation-session-repair.md)를 따른다. 해석·메모리·MCP 도구 선택 호출이 generation으로 기록된다.
