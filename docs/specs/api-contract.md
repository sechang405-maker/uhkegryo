# Agent 공개 API 계약

## Why

자연어 해석과 검색은 오래 걸리거나 일시적으로 실패할 수 있다. 세션 소유권, 비동기 job, 결과 상태, 자동 재시도 규칙을 하나의 공개 계약으로 고정한다.

## Goal

- 서버 세션 쿠키와 job polling으로 요청을 처리한다.
- LLM·검색 provider의 회복 가능한 오류는 사용자에게 노출하지 않고 최대 3회 자동 재시도한다.
- 사용자에게는 검증된 결과, 질문, 부분 결과 또는 일반 실패 안내만 보여 준다.

## What

| Endpoint | Method | 성공 | 오류 |
| --- | --- | --- |
| `/health` | GET | `200 {"status":"ok"}` | — |
| `/api/agent` | POST | `202 {job_id, job_status:"queued", poll_after_ms:1000}`와 신규·기존 서버 세션의 HttpOnly cookie | `409 IDEMPOTENCY_KEY_CONFLICT`, `422 INVALID_REQUEST_TEXT` |
| `/api/jobs/{job_id}` | GET | `200 JobEnvelope` | `401 SESSION_REQUIRED`, `404 JOB_NOT_FOUND` |

`POST /api/jobs/{job_id}/retry`는 없다. 사용자의 후속 메시지는 새 job이다.

HTTP 오류 본문은 종결 실패의 `Failure`와 같은 형태인 `{failure_code, user_message, retryable:false}`를 쓴다. 다만 코드는 job 종결 실패용 13종(`FailureCode`)과 요청 단계 거절용 4종(`ApiErrorCode` = `INVALID_REQUEST_TEXT`, `IDEMPOTENCY_KEY_CONFLICT`, `SESSION_REQUIRED`, `JOB_NOT_FOUND`)으로 분리한다. `INVALID_REQUEST_TEXT`는 본문 형식 위반, 공백만 있는 `request_text`, 1~500자 범위 이탈, 허용하지 않은 추가 필드, 그리고 없거나 UUID 형식이 아닌 `Idempotency-Key`를 함께 다룬다. `user_message`는 사용자에게 보여 줄 문구이며 내부 오류 원문과 비밀값을 담지 않는다.

`AgentRequest`는 공백만으로 이루어지지 않은 `request_text` 1~500자와 선택적 UUID `session_id`를 가진다. 허용하지 않은 추가 필드는 거부한다. `POST /api/agent`는 유효한 기존 세션 쿠키가 있으면 재사용하고, 없으면 서버가 새 익명 세션을 발급해 동일 응답에 HttpOnly cookie로 설정한다. 브라우저는 `role`, `term_id`, 검색어, Pin URL, 세션 토큰, `anonymous_user_id`를 전송하지 않는다. 요청은 UUID `Idempotency-Key` 헤더가 필요하며, 10분 안에 같은 세션·키·원문을 재전송하면 기존 job을 반환한다. 유효 세션의 API 활동마다 세션 쿠키는 `Max-Age=달력 기준 3개월`로 갱신되고 토큰 값은 바뀌지 않는다(`session-job-persistence.md`).

`JobEnvelope`는 `job_id`, `session_id`, `job_status`, `attempt`, `max_attempts`, `poll_after_ms`, `result`, `failure`를 가진다. DB 신규 job은 `attempt=0`으로 저장하지만 API는 queued 상태를 포함해 `attempt=1..max_attempts`만 노출한다. 따라서 claim 전 queued job은 `attempt=1`로 응답하고, worker가 claim하면 DB 값을 1로 증가시켜 첫 실행을 시작한다. 재시도는 `2`, `3`으로 증가하며 `3`을 초과해 실행하지 않는다. `job_status`는 `queued | running | validating | searching | rendering | completed | failed`이고 `completed`, `failed`만 종결 상태다. 진행 상태는 `result=null`, `failure=null`, `poll_after_ms=1000`이다. `completed`는 `result` 필수, `failure=null`, `poll_after_ms=null`이다. `failed`는 `result=null`, `failure` 필수, `poll_after_ms=null`이다.

현재 `AgentResult`는 `agent_status`, `reason_codes`, `reference_plan`, `clarifying_question`, `user_message`를 가진다. `agent_status`는 `success | needs_clarification | out_of_scope | unsafe_input | partial_result`다. 서버가 LLM 후보·카탈로그·안전·검색 결과를 조립해 결정한다. `service_unavailable`은 사용하지 않는다. `clarification_choices`는 [선택형 후속 질문 Spec](./clarification-choices.md)의 schema·resolver·assembler·adapter·Prompt·테스트 구현 후 활성화할 예정 필드이며 현재 응답에는 없다.

`ReferencePlan`은 `terms`, `unresolved_roles`를 가진다. `terms`는 역할당 최대 하나의 활성 TERM_CARD를 역할 순서대로 가진다. 각 `TermResult`는 `role`, `term_id`, `label_ko`, `label_en`, `plain_meaning_ko`, `selection_reason`, `reference_checkpoints`, `search_url`, `pins`, `reason_codes`를 가진다. `pins`는 역할별 최대 8개이며 SearXNG provider가 반환한 원래 순서를 보존한다. 검색은 [SearXNG Pinterest 검색 Spec](./searxng-pinterest-search.md)의 Pinterest 단일 엔진 JSON API 계약을 따른다. provider는 Pinterest Pin ID·`pin_url`을 수집한 뒤 모든 Pin ID를 widget endpoint로 조회해 응답 전용 `thumbnail_url`을 조립한다. `TermResult.reason_codes`는 빈 배열, `PIN_RESULTS_EMPTY`, `PIN_SEARCH_UNAVAILABLE` 중 하나다. pins가 있으면 빈 배열, 정상 검색 0건이면 `PIN_RESULTS_EMPTY`, 검색 자체가 실패해 Pin을 수집하지 못하면 `PIN_SEARCH_UNAVAILABLE`을 반환한다. `AgentResult.reason_codes`는 역할 코드의 중복 없는 전체 집계다. `PinResult`는 `pin_id`, `pin_url`, 응답 전용 `thumbnail_url | null`, `status`를 가진다. `PinStatus`는 `available | deleted`다. `PIN_RESULTS_EMPTY`와 `PIN_SEARCH_UNAVAILABLE`은 Pin 상태가 아니라 역할 결과의 reason code다.

`TermResult` 피드백은 JSON에서만 조립하며 LLM이 만들지 않는다. `active_term_feedback[term_id]`가 있으면 `plain_meaning_ko <- plain_meaning_ko`, `selection_reason <- selection_reason_template_ko`, `reference_checkpoints <- reference_checkpoints_ko`다. 해당 피드백이 없으면 `plain_meaning_ko <- source_answer_draft`, `selection_reason=null`, `reference_checkpoints <- look_for`다.

`success`와 `partial_result`만 `reference_plan`을 반환한다. `needs_clarification`은 `reference_plan=null`, 비어 있지 않은 `clarifying_question`을 반환한다. `out_of_scope`와 `unsafe_input`도 `reference_plan=null`이며 `clarifying_question=null`이다. 모든 상태의 `reason_codes`는 배열이다. 후속 선택지 구현 후에는 모든 `AgentResult`에 `clarification_choices` 배열을 추가하며, 활성화 조건과 빈 배열 처리 규칙은 [선택형 후속 질문 Spec](./clarification-choices.md)을 따른다.

`reason_codes` enum은 `ABSTRACT_INTENT_ONLY`, `INSUFFICIENT_VISUAL_EVIDENCE`, `CONFLICTING_CONSTRAINTS`, `DIRECT_SEARCH_DISABLED`, `PIN_RESULTS_EMPTY`, `PIN_SEARCH_UNAVAILABLE`, `OUT_OF_SCOPE_REQUEST`, `UNSAFE_INPUT`이다. `success`는 빈 배열만, `partial_result`는 `PIN_RESULTS_EMPTY` 또는 `PIN_SEARCH_UNAVAILABLE`만, `needs_clarification`은 `ABSTRACT_INTENT_ONLY`·`INSUFFICIENT_VISUAL_EVIDENCE`·`CONFLICTING_CONSTRAINTS`·`DIRECT_SEARCH_DISABLED` 중 하나 이상과 질문 하나를 반환한다. `out_of_scope`는 `OUT_OF_SCOPE_REQUEST`만, `unsafe_input`은 `UNSAFE_INPUT`만 반환한다. 코드 배열은 중복을 허용하지 않는다.

최종 실패는 `result=null`과 `failure={failure_code,user_message,retryable:false}`를 가진다. API에 노출하는 `failure_code` enum은 `LLM_TIMEOUT`, `LLM_RATE_LIMITED`, `LLM_UPSTREAM_UNAVAILABLE`, `LLM_INVALID_STRUCTURED_OUTPUT`, `SEARCH_TIMEOUT`, `SEARCH_RATE_LIMITED`, `SEARCH_UPSTREAM_UNAVAILABLE`, `JOB_INSTANCE_INTERRUPTED`, `CONFIGURATION_ERROR`, `DATABASE_MIGRATION_ERROR`, `DATABASE_UNAVAILABLE`, `CATALOG_INVALID_AT_STARTUP`, `INTERNAL_CODE_ERROR`이다.

## How

역할별 보드 갱신 worker 응답의 `AgentResult.reference_update`는 `replaced_roles`, `preserved_roles`, `removed_roles` 배열을 가진 nullable 객체다. 정상·부분 결과와 확인 질문에서 서버가 조립하며, 질문의 `reference_plan=null` 규칙은 유지한다. 기존 저장 응답에는 null 기본값을 사용한다. 상세 불변 조건과 수용 기준은 `reference-update-metadata.md`, 일부 역할 이미지 교체 계약은 `reference-role-refresh.md`를 따른다.

- 실패 코드의 타입·호출 경계별 매핑과 고정 안내 문구는 [failure-code-mapping.md](./failure-code-mapping.md)를 따른다. API 저장소의 연결·인증·스키마 오류는 HTTP 503과 분류된 `Failure`를 반환하며, 예상하지 않은 코드 오류는 HTTP 500과 `INTERNAL_CODE_ERROR`를 반환한다.

- 세션 쿠키의 발급·달력 기준 3개월 갱신, session/job 저장 구조, idempotency 저장 규칙은 [session-job-persistence.md](./session-job-persistence.md)가 단일 기준이다. `GET /api/jobs/{job_id}`는 이 쿠키를 검증하며, job 조회에서 세션이 job 소유자가 아니어도 `JOB_NOT_FOUND`를 반환한다.
- Next.js 프론트는 `NEXT_PUBLIC_API_BASE_URL=/api`와 `credentials:"include"`를 사용한다. 브라우저는 FastAPI origin을 직접 호출하지 않는다. Next.js rewrite가 동일 origin의 `/api/*` 요청을 내부 FastAPI로 전달하며, BFF가 필요해질 때만 Route Handler를 추가한다. 세션 토큰·`anonymous_user_id`를 localStorage, URL, 로그에 저장하지 않는다.
- worker의 polling, lease, 세션별 실행 순서와 재실행은 [postgres-job-worker.md](./postgres-job-worker.md)가 단일 기준이다. 같은 job은 최초 실행을 포함해 최대 3회이며 LLM 회복 가능 실패 뒤에는 `next_retry_at` 전까지 재실행하지 않는다. `next_retry_at`의 저장 계약은 [session-job-persistence.md](./session-job-persistence.md)가 단일 기준이다. LLM 오류별 재시도·backoff·최종 failure code는 [openrouter-llm-adapter.md](./openrouter-llm-adapter.md)가 단일 기준이다. worker는 job당 하나의 Langfuse trace를 유지하고, adapter·검색·결과 조립 단계는 그 trace에 observation/span을 추가한다.
- `CONFIGURATION_ERROR`, `DATABASE_MIGRATION_ERROR`, `INTERNAL_CODE_ERROR`는 즉시 `failed`다. 사용자 UI는 failure code·오류 원문·비밀값을 보이지 않고 “현재 요청을 처리하지 못했습니다. 잠시 후 새 메시지로 다시 시도해 주세요.”만 표시한다.
- 단서 부족·상충은 실패가 아니라 `completed + needs_clarification`이며 질문 하나를 반환한다. 다음 사용자 메시지는 새 job이고 기존 attempt를 승계하지 않는다.
- `partial_result`의 UI `같은 조건으로 다시 찾기`는 메모리에 남은 원래 `request_text`를 새 UUID 키로 제출해 새 job을 만든다. `검색 링크 열기`는 실패 역할의 `search_url`을 새 탭에서 열고, `조건 바꿔 입력하기`는 원문을 편집하도록 채운다. 기존 job을 retry하는 endpoint는 만들지 않는다.
- LLM adapter는 `InterpretationOutput={interpretation_state, clarification_type, selections, unresolved_constraints, clarifying_question, context_updates, answer_text}`만 반환한다. `interpretation_state`는 `select_terms | needs_clarification` enum이고, 허용하지 않은 추가 필드는 거부한다. 각 `selections` 항목은 `{role, term_id, evidence, confidence, source_job_id}`이며, `evidence`는 현재 요청 또는 지정된 동일 대화의 선행 원본 요청·카드 라벨에서 확인한 비어 있지 않은 표현의 배열(`list[str]`, 한 개 이상), `confidence`는 `0.0..1.0`이다. 역할은 중복되지 않고 `body → pose → view → perspective → layout` 순서를 따른다. resolver는 출처 원본에서 근거 문구를 확인하고 활성 카드 선택을 검증한다.
- `select_terms`이면 selections는 한 개 이상, `unresolved_constraints=[]`, `clarifying_question=null`, `clarification_type=null`이다. `needs_clarification`이면 selections는 빈 배열, `unresolved_constraints`는 비어 있거나 공백만으로 이루어지지 않은 항목을 한 개 이상 가지며, `clarifying_question`은 비어 있지 않은 한국어 질문 하나, `clarification_type`은 `abstract_intent | insufficient_visual_evidence | conflicting_constraints` 중 하나다. `clarification_type`은 최종 `reason_code`가 아닌 resolver가 다시 검증할 후보다. LLM의 `clarifying_question`은 구조 검증용이며 API 응답에는 전달하지 않고 resolver가 고정 질문을 조립한다.
- LLM은 최종 `agent_status`, `reason_codes`, 검색 URL을 만들지 않으며, resolver가 활성 JSON 카탈로그·안전 규칙과 대조한 뒤 최종 응답을 조립한다. 구조화 출력이 이 계약을 만족하지 않으면 `LLM_INVALID_STRUCTURED_OUTPUT`으로 처리한다. `requires_all_of`·`requires_any_of`는 카탈로그의 부모 `term_id` 의존 관계이며 LLM selection 목록의 추가 항목이 아니다. resolver는 부모 ID가 selection에 없다는 이유로 후보를 거부하지 않고, 선택 카드의 의존 그래프가 존재·활성·비순환인지 확인한다.
- resolver의 질문 사유 매핑은 아래와 같다. free-text `unresolved_constraints`만으로 최종 코드를 정하지 않으며, 요청 단서와 카드 조건을 함께 다시 검증한다.

| resolver가 검증한 조건 | 허용된 `clarification_type` 후보 | 최종 `reason_code` |
| --- | --- | --- |
| 구체적인 체형·포즈·시점·원근·구도 단서 없이 인상·의도만 있음 | `abstract_intent` | `ABSTRACT_INTENT_ONLY` |
| 역할 단서는 있으나 해당 카드의 `confidence_gate`를 충족할 단서가 없음 | `insufficient_visual_evidence` | `INSUFFICIENT_VISUAL_EVIDENCE` |
| 서로 양립할 수 없는 체형·시점·자세 조건이 동시에 명시됨 | `conflicting_constraints` | `CONFLICTING_CONSTRAINTS` |
| 유효한 카드가 선택됐지만 `direct_search_disabled_term_ids`에 포함됨 | 해당 없음 — LLM이 판단하지 않음 | `DIRECT_SEARCH_DISABLED` |
- 검색 provider는 서버에서 활성 카드의 `query_fragments`에 `drawing`을 추가해 SearXNG Pinterest 엔진 JSON API를 호출하고, 유효 Pin URL만 사용한다. SearXNG 엔진은 외부 원본 링크 대신 Pin ID로 canonical Pin URL을 반환한다. 다른 검색 엔진으로 fallback하지 않는다. 모든 수집 Pin ID는 widget endpoint로 조회한다. 브라우저는 검색·widget endpoint를 직접 호출하지 않으며 Pinterest API v5도 사용하지 않는다. 세부 검색 계약은 [SearXNG Pinterest 검색 Spec](./searxng-pinterest-search.md)을 따른다.
- 검색 provider 재시도가 소진돼도 하나 이상의 카드가 유효하면 `completed + partial_result`다. 실패 역할은 `pins=[]`, `PIN_SEARCH_UNAVAILABLE`을 반환하고 UI는 검색 결과 미수신 안내와 용어·검색 URL을 표시한다. 수집한 Pin의 widget·원본 접근 실패 또는 이미지 URL 부재는 `deleted` 상태로 반환한다. 정상 0건은 `PIN_RESULTS_EMPTY`이며 재시도하지 않는다.
- 잘못된 Secret·provider 인증 설정은 `CONFIGURATION_ERROR`, job/session 저장소 연결 불가는 `DATABASE_UNAVAILABLE`, 시작 JSON 카탈로그 검증 실패는 `CATALOG_INVALID_AT_STARTUP`, 코드 버그는 `INTERNAL_CODE_ERROR`로 즉시 실패한다. `CATALOG_INVALID_AT_STARTUP`이면 서비스는 ready가 아니며 job을 수신하지 않는다. 이 네 경우는 자동 재시도하지 않는다.
- provider 결과의 원격 썸네일은 `available`일 때만 표시하고 항상 원본 `pin_url`로 이동한다. widget이 이미지 URL을 주지 않거나 접근할 수 없으면 `deleted`와 접근 불가 안내를 반환한다. `pin_id`, `pin_url`, `status`는 세션·job 이력에 포함된 결과로만 유지하고 별도 Pin 저장소를 만들지 않는다. `GET /api/jobs/{job_id}`는 저장된 `pin_id`로 widget을 다시 조회해 응답 전용 `thumbnail_url`을 조립하며, 이 조회에서 접근할 수 없는 Pin은 `deleted`로 표시한다. widget의 이미지 바이트·`thumbnail_url`과 부가 Pin 필드는 저장·재게시·LLM 입력·trace·로그에 사용하지 않는다.

## AC

**AC-01 · 비동기 제출**

- GIVEN: 1~500자 입력이 있다.
- WHEN: `POST /api/agent`로 요청을 제출한다.
- THEN: 신규 세션은 HttpOnly cookie를 발급하고, 기존 세션은 이를 재사용하며, `202`와 queued job을 반환한다.
- AND THEN: 프론트는 종결까지 polling한다.

**AC-02 · 자동 재시도**

- GIVEN: 회복 가능한 LLM 또는 검색 오류가 있다.
- WHEN: worker가 처리한다.
- THEN: 사용자에게 중간 오류를 보이지 않고 최초 실행 포함 최대 3회 실행한다.

**AC-03 · 검색 부분 결과**

- GIVEN: 유효 카드가 있고 검색 provider 재시도가 소진된다.
- WHEN: 결과를 조립한다.
- THEN: `completed + partial_result`, 빈 pins, `PIN_SEARCH_UNAVAILABLE`을 반환한다.

**AC-04 · 최종 실패 코드**

- GIVEN: 재시도 소진 또는 결정적 운영 오류가 발생한다.
- WHEN: job을 종결한다.
- THEN: API는 안정된 `failure_code`를 포함한다.
- AND THEN: UI는 일반 실패 문구만 표시한다.

**AC-05 · 동일 origin API 호출**

- GIVEN: 배포된 Next.js 프론트가 있다.
- WHEN: 브라우저가 API를 호출한다.
- THEN: `/api/*` 상대 경로와 세션 쿠키만 사용한다.
- AND THEN: FastAPI origin으로 직접 cross-origin 요청하지 않는다.

**AC-06 · polling 종료**

- GIVEN: job 조회 응답이 있다.
- WHEN: job이 진행 중이다.
- THEN: `poll_after_ms=1000`을 반환한다.
- WHEN: job이 `completed` 또는 `failed`다.
- THEN: `poll_after_ms=null`을 반환한다.

**AC-07 · TERM_CARD 피드백 조립**

- GIVEN: 활성 카드와 `active_term_feedback[term_id]`가 있다.
- WHEN: `TermResult`를 조립한다.
- THEN: API 피드백 필드는 해당 JSON 피드백에서만 매핑한다.
- GIVEN: 활성 카드에 해당 피드백이 없다.
- WHEN: `TermResult`를 조립한다.
- THEN: `source_answer_draft`, `look_for`를 fallback으로 사용하고 LLM이 문구를 생성하지 않는다.

**AC-08 · HTTP 오류 본문**

- GIVEN: 형식이 잘못된 본문 또는 없거나 UUID가 아닌 `Idempotency-Key`, WHEN: `POST /api/agent`를 호출한다, THEN: `422`와 `{failure_code:"invalid_request_text", user_message, retryable:false}`를 반환한다.
- GIVEN: 10분 안에 같은 세션·키·다른 원문, WHEN: `POST /api/agent`를 호출한다, THEN: `409`와 `{failure_code:"idempotency_key_conflict", user_message, retryable:false}`를 반환한다.
- GIVEN: 세션 쿠키 없이 `GET /api/jobs/{job_id}`를 호출한다, THEN: `401`과 `{failure_code:"session_required", user_message, retryable:false}`를 반환한다.
- GIVEN: job이 없거나 현재 세션이 소유자가 아니다, WHEN: `GET /api/jobs/{job_id}`를 호출한다, THEN: `404`과 `{failure_code:"job_not_found", user_message, retryable:false}`를 반환한다.
- AND THEN: 모든 오류 본문은 `failure_code`·`user_message`·`retryable` 세 필드만 갖고, `user_message`에 내부 오류 원문이나 비밀값을 담지 않는다.

## 대화 기억 확장

대화 생성·목록·열람·이력 API와 기존 기본 대화 호환은 [conversation-sessions.md](conversation-sessions.md)를 따른다. 유효한 소유자라도 타인/만료 대화는 404 session_not_found이며 job은 job_not_found다. 브라우저가 전달한 맥락·요약은 거부한다.

AgentResult는 nullable memory_answer(최대 2000자)와 sources 배열(job_id, 서버가 만든 /api/jobs/{id} href)을 추가한다. agent_status=memory_answer는 reference_plan=null, reason_codes=[], clarifying_question=null이다. 출처 없는 응답은 '이 대화 기록에서 해당 내용을 확인할 수 없습니다.' 또는 '관련 기록이 많습니다. 어느 시기 또는 어떤 추천을 말씀하시나요?'로만 제한한다. 일반 해석 결과에도 회상 답과 출처를 함께 담을 수 있다. 상세 계약은 [conversation-recall.md](conversation-recall.md)를 따른다.

회상 전용 job은 validating에서 rendering으로 바로 전이한다. 조건 변경·원문 evidence·출처 검증은 [conversation-context.md](conversation-context.md), 요약 범위는 [conversation-summary.md](conversation-summary.md)를 따른다. source_job_id가 null이면 evidence는 현재 원문, 값이 있으면 해당 대화의 선행 원본 요청/카드 라벨을 인용한다. 상태의 최종 결정은 서버가 한다.
`answer_text`는 InterpretationOutput와 AgentResult의 최대 4,000자 strict 문자열(기본 빈 문자열)이다. resolver 검증 후 일반/부분 결과에만 모델 통합 설명을 노출하며 term별 정적 피드백·회상 답변은 기존 계약을 유지한다. UI 복원과 상세 계약은 [studio-conversation-connection.md](studio-conversation-connection.md)를 따른다.

모호·상충 확인 질문은 모델 문장을 직접 전달하지 않는다. resolver가 clarification_type과 현재 요청의 제한된 시각 단서를 이용해 고정된 지지 다리/S자 흐름·체형/의상·어깨/골반 비율·옆모습/정면 질문을 고르며, 해당되지 않으면 기존 공통 질문을 반환한다. v4의 검증 실패 피드백과 답변 안내는 [ambiguity-answer-quality.md](ambiguity-answer-quality.md)를 따른다.
