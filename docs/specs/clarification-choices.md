# 선택형 후속 질문 (예정 계약)

## Why

- **페르소나**: 드로잉 용어를 모르는 초보 사용자
- **상황**: 해석 결과가 `needs_clarification`이면 질문을 보고 다음 요청을 직접 작성해야 한다.
- **문제**: 답변 예시가 없으면 사용자가 어떤 시각 조건을 적어야 하는지 알기 어렵다. LLM 자유 문장으로 새 요청을 만들면 기존 조건 보존과 상충 해소를 검증할 수 없다.
- **측정 지표**: 공개 선택지의 활성 카드 ID 위반 0건, 허용 조건 밖 선택지 0건, 500자 초과 재입력 문장 0건

## Goal

- LLM은 활성 TERM_CARD의 제한된 `{role, term_id}` 후보만 제안하고, 서버가 표시 문구와 새 요청 문장을 조립한다.
- 확정 조건이 없는 `ABSTRACT_INTENT_ONLY` 질문에서만 2~3개의 선택지를 제공한다. 그 외 질문은 직접 입력으로 처리한다.
- **Out of Scope**: 상충 문장 자동 수정, 기존 Job 재시도 endpoint, 대화 이력, 자유 문장 선택지 생성

## What

1. 현재 배포 계약에는 `clarification_choices`와 LLM 후보 필드가 없다. `AgentResult`, `InterpretationOutput`, `ResolutionResult`, resolver, assembler, adapter, Prompt, worker 연동 및 AC 테스트가 완료된 뒤 함께 활성화한다. 그전까지 UI는 필드가 없는 응답을 빈 선택지로 취급한다.
2. 후속 구현에서 `InterpretationOutput`에 `clarification_candidates: list[{role, term_id}]`를 추가한다. `select_terms`에서는 빈 배열이다. `needs_clarification` 중 `clarification_type=abstract_intent`일 때만 LLM이 활성 카드 중 동일 역할의 서로 다른 후보 2~3개를 제안하며, 다른 질문 유형에서는 빈 배열이다. 후보는 확정된 `selections`가 아니며 `selections=[]`를 유지한다. LLM은 `label`이나 `request_text`를 출력하지 않는다.
3. resolver의 최종 사유가 `ABSTRACT_INTENT_ONLY`이고 원문이 아래의 검수된 인상어 문장 허용 목록에 정확히 속할 때만 후보를 승인한다. `INSUFFICIENT_VISUAL_EVIDENCE`, `CONFLICTING_CONSTRAINTS`, `DIRECT_SEARCH_DISABLED`, 안전 거절 및 다른 최종 상태에서는 공개 선택지가 빈 배열이다. 상충한 원문을 기계적으로 고치지 않는다.
4. 승인된 선택지는 `AgentResult.clarification_choices: list[{label, request_text}]`로 제공한다. 사용자가 칩을 선택하면 UI가 `request_text`를 편집 가능한 입력창에 채운다. 전송은 사용자가 명시적으로 누를 때 새 UUID `Idempotency-Key`의 새 Job으로 수행한다.
5. 승인된 후보가 2개 미만이거나 조립된 문장 중 하나라도 계약을 어기면 선택지 전체를 비우고 기존 `clarifying_question`을 유지한다. UI는 모든 질문에서 직접 입력을 제공한다.

## How

- 후보의 `role`은 다섯 역할 enum 중 하나이고, `term_id`는 시작 검증을 통과한 활성 카드에 존재해야 하며 해당 역할과 일치해야 한다. 후보는 모두 동일 역할이고 ID가 서로 달라야 한다. `direct_search_disabled_term_ids`와 부모 카드 의존(`requires_all_of` 또는 `requires_any_of`)이 있는 카드는 선택지에서 제외한다.
- resolver는 LLM의 `clarification_type`만 믿지 않고 기존 질문 사유 검증을 거쳐 최종 `ABSTRACT_INTENT_ONLY`를 확정한다. 추가로 원문을 앞뒤 공백 제거와 연속 공백 하나로만 정규화한 값이 `멋진 캐릭터`, `자연스러운 캐릭터`, `캐릭터를 그리고 싶어요` 중 하나인지 정확히 비교한다. 이 허용 목록은 시각 조건이 없는 문장만 포함하며 목록 밖 요청은 의미를 추측하지 않고 후보를 모두 버린다. 따라서 원문에서 보존·교체할 시각 조건이 있는 경우 자동 선택지를 만들지 않는다.
- 공개 `label`은 검증된 카드의 `label_ko` 그대로 사용한다. 같은 표시 문구가 중복되면 해당 후보를 버린다. LLM 자유 텍스트는 표시 문구에 쓰지 않는다.
- 역할별 고정 이름은 `body=체형`, `pose=포즈`, `view=시점`, `perspective=원근`, `layout=배치`다. 공개 `request_text`는 `정규화한 원문 + "\n원하는 " + 역할 이름 + ": " + 카드 label_ko + "."`로만 조립한다. 원래 요청을 삭제·요약·재작성하지 않으며 카드 밖 문자열을 추가하지 않는다. 조립 후 공백만으로 이루어졌거나 전체 길이가 1~500자를 벗어나면 선택지 전체를 비운다.
- 선택지가 승인되면 질문은 해당 역할의 고정 문구(`원하는 체형은 무엇인가요?`, `원하는 포즈는 무엇인가요?`, `원하는 시점은 무엇인가요?`, `원하는 원근 표현은 무엇인가요?`, `원하는 배치는 무엇인가요?`)로 대체한다. 선택지가 비면 기존 `clarifying_question`을 유지한다.
- `AgentResult` 필드가 활성화된 뒤에는 모든 상태에서 `clarification_choices`를 반환한다. 위 조건에 맞는 `needs_clarification`에서만 2~3개이고 나머지는 `[]`다. LLM 후보 형식 오류는 기존 구조화 출력 재시도 정책을 따르고, resolver의 후보 거절은 Job 실패가 아닌 빈 선택지로 처리한다.
- 후속 구현 범위: `backend/schemas/models.py`의 두 출력 모델, `backend/services/resolver.py`와 `ResolutionResult`, `backend/services/response_assembler.py`, `backend/services/llm.py`의 구조화 출력 계약, `backend/services/agent_worker.py`의 원문 전달·결과 연결, `prompts/uhkegryo-interpreter-v0.md`, 해당 단위·API 계약 테스트, Next.js 질문 칩 UI. PR당 코드 변경 400줄 제한을 지켜 독립 PR로 분리한다.

## AC

**AC-01 · 제한된 후보와 서버 조립**

- GIVEN: 확정된 시각 조건이 없는 요청과 `ABSTRACT_INTENT_ONLY`, 동일 역할의 활성·검색 가능·부모 의존 없는 카드 후보 2~3개가 있다.
- WHEN: resolver와 assembler가 결과를 만든다.
- THEN: `label`은 각 카드의 `label_ko`이고, `request_text`는 원문과 고정 역할 문구만으로 조립되며 LLM 자유 문장이 포함되지 않는다.
- GIVEN: 원문이 `멋진 캐릭터`이고 후보에 `{role:"view", term_id:"view_front"}`가 있다.
- WHEN: 시점 후보가 승인된다.
- THEN: 해당 선택지는 `{label:"프론트 뷰", request_text:"멋진 캐릭터\n원하는 시점: 프론트 뷰."}`다.

**AC-02 · 상충·불충분 조건의 폴백**

- GIVEN: 최종 사유가 `CONFLICTING_CONSTRAINTS`, `INSUFFICIENT_VISUAL_EVIDENCE` 또는 `DIRECT_SEARCH_DISABLED`다.
- WHEN: 후보가 있어도 결과를 조립한다.
- THEN: `clarification_choices=[]`이고 기존 질문과 직접 입력 경로를 유지한다.

**AC-03 · 후보 검증 실패**

- GIVEN: 카드 밖 ID, 역할 불일치, 중복 ID·표시 문구, 직접 검색 금지 카드, 부모 의존 카드, 또는 500자를 넘는 조립 문장이 있다.
- WHEN: 후보를 검증한다.
- THEN: 부적합 후보를 제외하고 남은 후보가 2개 미만이면 선택지 전체를 비우며 Job 상태를 실패로 바꾸지 않는다.

**AC-04 · 활성화 경계**

- GIVEN: 후속 schema·resolver·assembler·adapter·Prompt·테스트 구현이 배포되지 않았다.
- WHEN: 현재 API가 질문 결과를 반환한다.
- THEN: 새 후보 필드를 LLM에 요구하지 않고 API에도 `clarification_choices`를 추가하지 않는다. UI는 필드 부재를 빈 선택지로 처리한다.
