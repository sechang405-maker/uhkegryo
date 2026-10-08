# Contract Evaluation Variants

> **상태: 현재 계약 이행 완료.** `evals/contract-variants.jsonl`의 70개 고정 변형은 최신 비동기 job
> 계약을 사용한다. 30개 원문과 함께 계약 준수 평가 입력으로 사용하되, 실제 실행 전에는 baseline·Langfuse
> Dataset·출시 게이트의 측정 수치를 주장하지 않는다.

## Why

- 현재 `evals/dataset.jsonl`의 30개 원문은 의미 품질과 사용자 흐름을 평가한다.
- 같은 출력 계약이 어순, 동의어, 부정 표현, 공백·문장부호, 복합 조건이 달라져도 유지되는지는 별도로 확인해야 한다.
- 무작위 입력을 매 실행마다 만들면 개선 전후의 회귀 결과를 비교할 수 없으므로, 70개의 고정 변형을 버전 관리한다.
- 공개 API는 비동기 job 계약이므로, 변형도 동기식 단일 응답이 아니라 제출과 종결 결과를 구분해 검증해야 한다.

## Goal

- `evals/contract-variants.jsonl`에 70개의 유효한 JSONL 레코드를 추가한다.
- 30개 원문과 70개 변형을 합쳐 100건 이상의 계약 준수 평가를 재현 가능하게 만든다.
- 모든 변형은 팀 정적 TERM_CARD만 전제로 하며, Getty 등 외부 어휘 API·URI·provider 결과를 요구하지 않는다.
- 모든 변형은 최신 `docs/specs/api-contract.md`의 `POST /api/agent` 제출, job polling, 종결
  `JobEnvelope`와 `AgentResult` 또는 `failure`를 검증한다.

## What

1. 각 변형은 `id`, `source_eval_id`, `transform_kind`, `input`, `runtime_fixture`, `expected`, `why`를 가진다.
2. `source_eval_id`는 `evals/dataset.jsonl`의 `EVAL-01`부터 `EVAL-30` 중 하나를 참조한다.
3. `transform_kind`는 `word_order`, `synonym`, `negation`, `whitespace_punctuation`, `compound_constraint` 중 하나다.
4. `expected`는 제출 단계의 `202 + queued`와 polling한 종결 job을 구분한다. 종결 job은
   `completed + AgentResult` 또는 `failed + failure` 중 하나다.
5. 변형 전후 계약이 같으면 원문의 허용 선택·금지 행동·종결 상태를 보존한다. 부정 또는 복합 조건으로 계약이 바뀌면 변형 행의 `expected`에 변경된 상태·사유 코드·허용 선택을 명시한다.
6. 이 파일은 계약 평가용이다. 초보자 안내 품질의 사람 평가 점수는 원문 30개 평가에서만 기록한다.

## How

- 변형 행은 자동 난수 생성 결과가 아니라 사람이 검토 가능한 고정 JSONL 데이터로 저장한다.
- 70개는 다섯 변형 유형을 모두 포함하고, 각 유형은 최소 10건 이상 포함한다.
- 제출 기대값은 `POST /api/agent`의 `202`, `job_status="queued"`, `poll_after_ms=1000`을 확인한다.
- 종결 기대값은 `job_status`가 `completed` 또는 `failed`인지 먼저 확인한다. `completed`면
  `agent_status`, `reason_codes`, `reference_plan`, 선택·금지 term을 확인하고, `failed`면
  `result=null`, 안정된 `failure_code`, `retryable=false`를 확인한다.
- `agent_status`는 `success`, `needs_clarification`, `out_of_scope`, `unsafe_input`,
  `partial_result`만 사용한다. `service_unavailable`, `pending_human_review`와 이전 세부
  사유 코드는 사용하지 않는다.
- 사유 코드는 `ABSTRACT_INTENT_ONLY`, `INSUFFICIENT_VISUAL_EVIDENCE`,
  `CONFLICTING_CONSTRAINTS`, `DIRECT_SEARCH_DISABLED`, `PIN_RESULTS_EMPTY`,
  `PIN_SEARCH_UNAVAILABLE`, `OUT_OF_SCOPE_REQUEST`, `UNSAFE_INPUT`만 사용한다.
- `pins`는 역할별 최대 8개이며 `available`, `deleted`만 상태로
  사용한다. 원본 `pin_url` 링크와 응답 전용 `thumbnail_url`을 검증하되 `pinit.js`·Pin 데이터
  저장·재게시를 기대하지 않는다.
- `team_card` 카드와 현재 활성 `term_id`만 기대값에 사용한다. 외부 어휘 조회·Getty URI·외부 provider 폴백 관련 필드는 포함하지 않는다.
- 검증 스크립트 또는 정적 검사는 JSON 파싱, 정확히 70개인지, ID 중복 여부, 원문 참조 존재,
  변형 유형 분포, 활성 TERM_CARD·사유 코드·Pin 상태·외부 어휘 참조 부재를 확인한다.

70개 변형은 위 계약에 맞춰 제출과 종결 상태를 분리한다. `runtime_fixture`는 외부 Pin URL이 아닌
테스트 double 상태만 가지며, 검색 0건·재시도 소진·삭제 Pin·worker 중단은 최신 reason code와
failure code로 검증한다.

## AC

### AC-01 · 고정 변형 데이터

- GIVEN: `evals/dataset.jsonl`에 30개 원문이 있다.
- WHEN: 계약 평가 파일을 읽는다.
- THEN: `evals/contract-variants.jsonl`은 70개의 유효한 JSONL 레코드를 반환한다.

### AC-02 · 원문 추적성

- GIVEN: 모든 변형 행의 `source_eval_id`가 있다.
- WHEN: 원문 평가셋 ID와 대조한다.
- THEN: 누락된 원문 참조와 중복된 변형 ID가 없다.

### AC-03 · 계약 보존

- GIVEN: 어순·동의어·공백·문장부호 변형이 있다.
- WHEN: 계약 평가를 실행한다.
- THEN: 원문과 같은 허용 `term_id`, 종결 job 상태, `AgentResult` 상태, 금지 행동, 검색 계획을 기대한다.
- AND THEN: 제출은 `202 + queued`이고 polling은 같은 종결 결과를 반환한다.

### AC-04 · 조건 변경 처리

- GIVEN: 부정 또는 복합 조건 변형이 있다.
- WHEN: 변형 조건이 원문의 선택을 무효화하거나 충돌시킨다.
- THEN: 변형 행은 `needs_clarification`, `out_of_scope`, `unsafe_input` 또는 수정된 선택 계약을 명시하고 임의 선택을 허용하지 않는다.
- AND THEN: `needs_clarification`은 허용된 사유 코드와 질문 하나를, `out_of_scope`는
  `OUT_OF_SCOPE_REQUEST`만, `unsafe_input`은 `UNSAFE_INPUT`만 가진다.

### AC-05 · 자체 카드 경계

- GIVEN: 모든 계약 평가 행이 있다.
- WHEN: 외부 어휘 서비스·URI·provider 필드를 검사한다.
- THEN: Getty 및 외부 어휘 API를 요구하거나 반환하도록 기대하는 행이 없다.

### AC-06 · Pin과 실패 상태

- GIVEN: 검색 0건, 검색 재시도 소진, 삭제 Pin 또는 worker 실패 fixture가 있다.
- WHEN: 종결 job을 읽는다.
- THEN: 0건은 `completed + partial_result + PIN_RESULTS_EMPTY`, 검색 재시도 소진은
  `completed + partial_result + PIN_SEARCH_UNAVAILABLE`, 삭제 Pin은 `deleted` 상태로
  검증한다.
- AND THEN: worker 최종 실패는 `failed`, `result=null`, 허용된 `failure_code`로 검증하며
  `service_unavailable`을 반환하지 않는다.
