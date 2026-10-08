# TERM_CARD JSON 카탈로그 계약

## Why

팀이 검수한 전문용어만 LLM 선택·화면 설명·검색 계획에 사용하려면, 카드 원본과 검증 규칙이 하나여야 한다.

## Goal

- `index.json`과 index가 선언한 역할별 JSON을 TERM_CARD의 런타임 단일 원본으로 사용한다.
- 활성 카드 수를 고정하지 않고 카탈로그에서 동적으로 계산한다.
- 카탈로그가 유효하지 않으면 앱을 ready 상태로 만들지 않는다.

## What

앱 시작 시 index의 `categories` 순서대로 `body`, `pose`, `view`, `perspective`, `layout` JSON만 읽는다. 활성 조건 `runtime_eligible=true && mvp_status=active_in_current_contract`를 통과한 카드를 `term_id -> card` 메모리 사전과 역할별 목록으로 로드한다. 요청 처리 중 파일을 다시 읽지 않는다.

카드 변경은 JSON 수정, PR 검수, 배포, 새 인스턴스 시작 순서로 반영한다. TERM_CARD는 DB에 적재하거나 외부 어휘·Getty 데이터를 병합하지 않는다.

## How

시작 검증은 다음을 모두 확인한다.

- index와 index가 선언한 모든 역할 파일 존재
- JSON 파싱 가능
- 전역 고유 `term_id`
- 카드 `role`과 선언된 역할 일치
- `term_id`, `role`, `label_ko`, `label_en`, `query_fragments`, `look_for`, `confidence_gate`, `requires_all_of`, `requires_any_of`, `runtime_eligible`, `mvp_status` 필수 필드 존재
- 활성 카드의 비어 있지 않은 `query_fragments`
- 활성 카드의 비어 있지 않은 `source_answer_draft`, `look_for`
- 허용 역할과 활성 조건 유효성
- 모든 `requires_all_of`·`requires_any_of`의 부모 `term_id`가 카탈로그에 존재하고, 활성 카드가 참조하는 부모도 활성 상태인지
- `requires_all_of`·`requires_any_of`를 합친 의존 그래프에 순환이 없는지
- `active_term_feedback`의 모든 term ID가 활성 카드에 연결되는지
- 연결된 피드백의 비어 있지 않은 `plain_meaning_ko`, `selection_reason_template_ko`, `reference_checkpoints_ko`

전체 카드 수, 활성 카드 수, `card_count`의 특정 값은 검증하지 않는다. 카탈로그 검증 실패는 `CATALOG_INVALID_AT_STARTUP` 운영 원인으로 기록하고 worker/job 수신을 시작하지 않는다.

`requires_all_of`·`requires_any_of`는 세부 카드가 전제하는 부모 `term_id`의 카탈로그 의존 관계다. 이는 LLM이 같은 역할의 부모 카드를 추가로 selection해야 한다는 뜻이 아니다. 예를 들어 `pose_legs_crossed_at_knee`를 고르면 해당 세부 포즈 하나만 `pose` 결과로 남고, resolver는 `pose_sitting`이 선택 목록에 없다는 이유로 거부하지 않는다. resolver가 검사하는 것은 선택 카드의 의존 그래프가 시작 검증을 통과했는지이며, 입력 단서의 의미 해석은 LLM의 `confidence_gate` 준수와 `evidence` 계약으로 분리한다.

모든 카드의 `source_type`은 `team_card`다. Getty URI·외부 어휘 결과·이미지·Pin 메타데이터는 카드에 저장하지 않는다.

Pinterest 검색어 조립기는 구현 시 검증된 활성 카드의 `query_fragments`만 카드 유래 입력으로 사용해야 한다. 결정론 URL 빌더만 기존 조각의 `drawing` 포함 여부를 검사하거나 제거하지 않고 결합한 검색어 끝에 고정 접미사 `drawing`을 무조건 한 번 추가해야 한다. 따라서 현재 `pose_gesture` 카드의 `gesture drawing`과 `action line reference` 조각을 결합한 최종 검색어는 `gesture drawing action line reference drawing`이다. LLM·UI·사용자 일상어는 검색어에 추가·교체하지 않는다.

화면 피드백은 `active_term_feedback[term_id]`를 우선한다. 이 경우 `plain_meaning_ko`, `selection_reason_template_ko`, `reference_checkpoints_ko`를 API의 `plain_meaning_ko`, `selection_reason`, `reference_checkpoints`로 각각 매핑한다. 피드백이 없는 새 활성 카드는 `source_answer_draft`를 `plain_meaning_ko`로, `look_for`를 `reference_checkpoints`로 사용하며 `selection_reason=null`이다. `pinterest_search_notice_ko`, `common_confusion_ko`, `clarifying_question_ko`는 검수용 비공개 메타데이터로 API와 UI에 노출하지 않는다. LLM은 fallback 문구를 보완하거나 새로 만들지 않는다.

`pinterest_search_contract.direct_search_disabled_term_ids`에 든 카드는 검색 계획에 사용할 수 없다. 해당 카드 또는 추상 의도만 후보이면 resolver는 Pinterest URL을 만들거나 provider를 호출하지 않고 `completed + needs_clarification`과 질문 하나를 반환한다. 다음 사용자 메시지에서 구체 단서를 얻은 뒤 검색 가능한 활성 카드가 선택된 경우에만 검색한다.

## AC

**AC-01 · 동적 활성 카드 로드**

- GIVEN: 구조적으로 유효한 index와 역할별 JSON이 있다.
- WHEN: 앱이 시작한다.
- THEN: 활성 조건을 통과한 모든 카드를 메모리에 로드한다.
- AND THEN: 카드 수가 바뀌어도 고정 수 검증으로 시작이 실패하지 않는다.

**AC-02 · 카탈로그 fail-closed**

- GIVEN: 선언 파일 누락, JSON 파싱 실패, 중복 ID 또는 필수 필드 누락이 있다.
- WHEN: 앱이 시작한다.
- THEN: ready 상태와 worker 시작을 거부한다.

**AC-03 · 런타임 선택 경계**

- GIVEN: 요청 처리 중 LLM 후보가 있다.
- WHEN: resolver가 후보를 검증한다.
- THEN: 메모리 사전에 존재하는 활성 카드만 선택·검색 계획에 사용한다.

**AC-04 · 직접 검색 금지 카드**

- GIVEN: 후보가 `direct_search_disabled_term_ids`에 있다.
- WHEN: resolver가 검색 계획을 만든다.
- THEN: URL·provider 호출 없이 `needs_clarification`과 질문 하나를 반환한다.

**AC-05 · 피드백 검증**

- GIVEN: 활성 카드 또는 `active_term_feedback` 항목이 있다.
- WHEN: 앱이 시작한다.
- THEN: fallback 필드와 연결된 피드백 필드가 비어 있거나 피드백 ID가 활성 카드에 없으면 ready 상태를 거부한다.

**AC-06 · 같은 역할의 부모 의존**

- GIVEN: `pose_legs_crossed_at_knee`처럼 같은 `pose` 역할의 부모 카드를 의존하는 활성 카드가 있다.
- WHEN: LLM 후보와 resolver가 해당 세부 카드를 처리한다.
- THEN: 세부 카드 하나만 `pose` selection으로 유지하고, 부모 ID의 별도 selection을 요구하지 않는다.
- AND THEN: 시작 검증은 부모 ID의 존재·활성 상태와 의존 그래프의 비순환성을 확인한다.
