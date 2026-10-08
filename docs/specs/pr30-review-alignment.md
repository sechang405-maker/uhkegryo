# PR #30 리뷰 요청 정합성

## Why

- **페르소나**: OpenRouter 해석 어댑터를 운영하는 서비스 담당자.
- **상황**: 리뷰에서 최신 OpenRouter 및 관측 명세와 어댑터 설정·Langfuse 구조가 다른 점을 발견했다.
- **문제**: 30초 timeout은 명세의 180초와 다르고, 모델 환경변수 이름이 다르며, 어댑터가 호출마다 독립 trace를 만들어 job attempt의 관측 맥락이 나뉠 수 있다.
- **측정 지표**: 모든 설정 기본값과 배포 예시가 OpenRouter 명세와 일치하고, 모든 adapter generation이 worker가 만든 동일 job trace에 포함된다.

## Goal

- `LLM_TIMEOUT_SECONDS` 기본값을 180초로 하고 모든 API 배포 문서와 예시를 일치시킨다.
- 모델 설정은 `LLM_MODEL`만 사용한다.
- adapter 호출은 `job_id`, `session_id`, `attempt`, `max_attempts`를 필수 입력으로 받고 `job_id`·`session_id` UUID 원문, 사용자 요청 원문, 모델, prompt version과 시도 정보를 기존 worker trace 아래 generation observation으로 기록한다.
- 세션 쿠키 토큰(원문·해시), API key, `anonymous_user_id` 원문은 trace와 로그에 기록하지 않는다.
- **Out of Scope**: worker 재시도·backoff 구현, job trace 생성·소유, Langfuse 원격 Prompt 등록, prompt 본문 변경.

## What

### Happy Path

1. API 설정은 `LLM_MODEL`과 `LLM_TIMEOUT_SECONDS`를 로드한다.
2. worker가 job 단위 Langfuse trace와 현재 observation context를 소유한다.
3. worker가 각 시도마다 job/session 식별자와 attempt 정보를 adapter에 전달한다.
4. adapter는 현재 worker trace context 아래 generation observation을 추가하고 요청 원문, `job_id`·`session_id` UUID 원문, 모델, prompt version, attempt, max attempts를 기록한다.
5. 일반 애플리케이션 로그에는 사용자 원문이나 원본 session ID를 기록하지 않는다.

### Edge Cases

| 상황 | 처리 방식 |
| --- | --- |
| `LLM_MODEL` 미설정 | 코드 기본값 `openai/gpt-4o-mini` 사용 |
| `LLM_TIMEOUT_SECONDS` 미설정 | 코드 기본값 180초 사용 |
| Langfuse 키 미설정 | 기존처럼 Langfuse 전송 없이 호출을 마친다 |
| Langfuse 키는 설정됐지만 worker trace context가 없음 | adapter는 새 root trace를 만들지 않고 observation 전송을 생략하며 안전한 debug 로그만 남긴다 |
| 관측 메타데이터에 인증·사용자 식별 비밀이 포함될 수 있음 | 세션 쿠키 토큰 원문·해시, API key, `anonymous_user_id` 원문은 기록하지 않는다 |
| 동일 job 재시도 | worker context에 연결된 같은 trace에 attempt별 generation을 추가한다 |

## How

- `Settings.llm_model`은 `LLM_MODEL`을 읽고 기본값은 `openai/gpt-4o-mini`다. `openrouter_model` 별칭이나 `OPENROUTER_MODEL` 폴백은 두지 않는다.
- `Settings.llm_timeout_seconds` 기본값은 `180.0`이며 환경변수 이름은 `LLM_TIMEOUT_SECONDS`다. OpenAI 호환 client에는 `max_retries=0`을 유지한다.
- `AgentInterpretationAdapter.interpret()`와 `LLMInterpretationAdapter.interpret()`은 키워드 전용 `job_id: str`, `session_id: str`, `attempt: int`, `max_attempts: int`를 받는다.
- Langfuse SDK의 current trace context를 확인한 뒤 `start_as_current_observation(as_type="generation", ...)`로 자식 observation을 추가한다. adapter는 root trace를 만들지 않는다.
- generation input에는 `{"request_text": <원문>}`을 넣는다. metadata에는 UUID 원문 `job_id`, UUID 원문 `session_id`, `attempt`, `max_attempts`를 기록하고 generation에는 모델명과 `prompt_version`을 기록한다.
- 원본 `session_id`는 일반 애플리케이션 로그에 기록하지 않는다. 세션 쿠키 토큰 원문·해시, API key, `anonymous_user_id` 원문은 trace와 로그에 기록하지 않는다.
- `.env.example`, `DEPLOYMENT.md`, API 배포 환경변수에서 `LLM_MODEL`, `LLM_TIMEOUT_SECONDS`를 문서화한다. MCP 서비스에는 이 LLM 설정을 추가하지 않는다.
- 설정 로딩, 180초 client timeout, model 인자, 관측 필드·trace 부모 관계와 키 없는 경우를 adapter 테스트로 검증한다.

## AC

**AC-01 · timeout 기본값**

- GIVEN: `LLM_TIMEOUT_SECONDS`가 설정되지 않았다.
- WHEN: `Settings`를 로드하고 OpenRouter client를 만든다.
- THEN: 설정과 client timeout은 180초다.

**AC-02 · model 환경변수**

- GIVEN: 환경변수 `LLM_MODEL`에 모델 식별자를 설정했다.
- WHEN: `Settings`를 로드하고 adapter를 호출한다.
- THEN: 해당 값이 OpenRouter 요청의 `model`로 전달된다.

**AC-03 · job 관측 context**

- GIVEN: worker가 job의 Langfuse trace context를 활성화하고 adapter에 job/session/attempt context를 전달한다.
- WHEN: LLM 호출이 성공한다.
- THEN: adapter는 새 root trace를 만들지 않고 현재 job trace 아래 generation을 추가하며 요청 원문, `job_id`·`session_id` UUID 원문, 모델, prompt version, attempt, max attempts를 기록한다.
- AND THEN: 세션 쿠키 토큰 원문·해시, API key, `anonymous_user_id` 원문은 trace에 포함하지 않고, 일반 로그에도 원문 `session_id`를 포함하지 않는다.

**AC-04 · Langfuse 비활성화**

- GIVEN: Langfuse 키가 설정되지 않았다.
- WHEN: adapter가 LLM 응답을 처리한다.
- THEN: Langfuse 네트워크 작업 없이 정상 결과를 반환한다.

**AC-05 · 일반 로그 개인정보 경계**

- GIVEN: 요청 원문과 원본 session ID가 adapter에 전달된다.
- WHEN: 일반 애플리케이션 로그를 기록한다.
- THEN: 로그에는 두 원문 값이 포함되지 않는다.
