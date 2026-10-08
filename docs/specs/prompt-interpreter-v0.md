# Prompt Interpreter v0

## Why

- **페르소나**: 캐주얼 캐릭터 일러스트 초보자. 포즈·체형·시점·원근의 전문용어를 모르지만 원하는 장면을 한국어로 설명할 수 있다.
- **상황**: 사용자는 일상어 설명을 입력하고, 서버는 그 설명을 검수된 TERM_CARD 후보로 바꿔 레퍼런스 탐색 계획을 만든다.
- **문제**: LLM이 자유 용어·검색어·최종 상태까지 만들면 카드 검수 범위를 벗어나거나, 모호한 묘사를 사실처럼 보완할 수 있다.
- **측정 지표**: 30건 평가셋의 계약 준수율 100%, 역할·용어 적절성 평균 1.5/2 이상, 경계 문항에서 임의 term_id 선택 0건.

## Goal

- `request_text`, 활성 TERM_CARD 축약 JSON, 서버가 제공하는 `session_context`를 받아 `InterpretationOutput` JSON을 반환한다.
- 출력 상태는 `select_terms`와 `needs_clarification` 두 가지로 제한한다.
- 질문 상태는 최종 `reason_code`가 아닌 `clarification_type` 후보 enum 하나를 반환해, resolver가 사유 코드와 사용자용 고정 질문을 결정할 수 있게 한다.
- 질문 선택지용 제한된 카드 후보는 [선택형 후속 질문 Spec](./clarification-choices.md)의 후속 구현 전까지 출력하지 않는다.
- System message는 영어로 유지하고, enum·role·`term_id`를 제외한 사람이 읽는 출력 문자열은 한국어로 반환한다.
- 활성 카드 밖 ID·역할, 자유 검색어·URL, 최종 API 상태·사유 코드, 사용자용 설명문을 LLM 출력에서 제거한다.

**Out of Scope**: Langfuse 원격 Prompt 등록·label 변경, 모델 호출 코드, Pydantic 구현, 최종 `AgentResult` 조립, Pinterest 검색, 이미지 생성·편집·분석, 안전 분류의 최종 결정.

## What

### Happy Path

1. LLM adapter는 서버가 검증해 메모리에 로드한 활성 카드의 축약 JSON과 `request_text`, 서버 `session_context`를 Langfuse Prompt에 전달한다.
2. Prompt는 입력의 실제 단서를 `body`, `pose`, `view`, `perspective`, `layout` 역할로 나눈다.
3. 각 역할당 최대 하나의 활성 `term_id`를 `evidence`, `confidence`와 함께 `select_terms` JSON으로 반환한다.
4. Pydantic은 출력 구조를, resolver는 카드 활성 상태·역할·카탈로그 의존 그래프를 다시 검증한다. `requires_all_of`·`requires_any_of`의 부모 ID는 추가 LLM selection이 아니다.

### Edge Cases

| 상황 | Prompt 출력 | 서버 후속 책임 |
| --- | --- | --- |
| 인상어만 있고 시각 단서가 없음 | `needs_clarification`, `clarification_type=abstract_intent`, 빈 selections, 질문 하나 | resolver가 `ABSTRACT_INTENT_ONLY`와 사용자용 고정 질문을 조립 |
| 체형·포즈·시점 단서가 부족함 | `needs_clarification`, `clarification_type=insufficient_visual_evidence`, 빈 selections, 질문 하나 | resolver가 `INSUFFICIENT_VISUAL_EVIDENCE`와 사용자용 고정 질문을 조립 |
| 체형 또는 시점 조건이 상충함 | `needs_clarification`, `clarification_type=conflicting_constraints`, 빈 selections, 질문 하나 | resolver가 `CONFLICTING_CONSTRAINTS`와 사용자용 고정 질문을 조립 |
| 카드 밖 용어가 더 익숙해 보임 | 카드 밖 ID를 만들지 않음 | resolver가 활성 카드만 통과시킴 |
| 요청 안에 시스템 지시 무시·비밀 노출 문구가 있음 | 그 문구를 따르거나 출력하지 않음 | 안전 gate가 `unsafe_input` 또는 `out_of_scope`를 최종 결정 |
| 구조화 출력이 JSON/Pydantic에 맞지 않음 | 해당 없음 | LLM adapter가 최대 3회 재시도 또는 안정된 failure 처리 |

## How

### Prompt 원본과 버전

- 검토 원본: `prompts/uhkegryo-interpreter-v0.md`
- Langfuse Prompt 이름: `uhkegryo-interpreter-v0`
- Langfuse의 `production` label은 팀 검토와 실제 실행 검증 뒤에만 부여한다.
- Prompt source에는 평가셋 30건의 입력·정답·예시를 넣지 않는다. 평가는 Prompt와 분리된 `evals/dataset.jsonl`로 수행한다.
- v0의 기준선 평가는 현행 비동기 API 계약에 맞춘 30건 평가셋이 이 브랜치에 반영된 뒤에만 기록한다. 그 전에는 평가 통과나 점수를 주장하지 않는다.

### Skill·Prompt·resolver 결합

| 단계 | 단일 책임 | 입력 원본 |
| --- | --- | --- |
| Langfuse System message | 자연어 의미 해석과 허용 후보 선택 | `prompts/uhkegryo-interpreter-v0.md`의 영어 System message. `skills/SKILL.md`의 LLM 선택 규칙을 같은 의미로 반영한다. |
| Langfuse User message | 요청과 허용 카드 후보 전달 | `request_text`, 시작 검증을 통과한 `active_cards_json` |
| Pydantic + resolver | 구조·활성 상태·역할·카탈로그 의존 그래프·안전·최종 상태 검증 | TERM_CARD index, 역할별 JSON, API 계약 |

한국어 `skills/SKILL.md` 전문을 두 번째 system message로 덧붙이지 않는다. Skill의 검색·최종 상태·피드백 조립 규칙은 resolver가 적용한다. `direct_search_disabled_term_ids`도 LLM이 판단하지 않고 resolver가 후보 검증 뒤 처리한다.

### 입력 변수

| 변수 | 제공자 | 허용 내용 |
| --- | --- | --- |
| `request_text` | `POST /api/agent` 요청 | 1~500자 사용자 자연어. 지시가 아니라 해석 대상 데이터 |
| `active_cards_json` | 시작 검증 뒤 메모리 카탈로그 | 활성 카드의 `role`, `term_id`, `label_ko`, `confidence_gate`, `requires_all_of`, `requires_any_of`만 포함한 JSON |

`active_cards_json`은 요청마다 외부에서 검색한 문서 조각이 아니며, 시작 시 검증한 정적 JSON 카탈로그의 축약본이다. 따라서 이 Prompt는 RAG를 사용하지 않는다.

`requires_all_of`·`requires_any_of`의 값은 카탈로그 안의 부모 `term_id`를 가리키는 의존 메타데이터다. 예를 들어 `pose_legs_crossed_at_knee`가 `pose_sitting`을 요구해도 LLM은 세부 포즈 하나만 `pose` selection으로 반환한다. 부모 ID를 같은 역할의 두 번째 selection으로 반환하지 않으며, resolver는 선택 결과가 아닌 카탈로그 의존 그래프의 존재·활성 상태·순환 여부를 검증한다.

### Pydantic 출력 계약

```text
InterpretationOutput
  interpretation_state: "select_terms" | "needs_clarification"
  clarification_type: "abstract_intent" | "insufficient_visual_evidence" | "conflicting_constraints" | null
  selections: list[Selection]
  unresolved_constraints: list[str]
  clarifying_question: str | null

Selection
  role: "body" | "pose" | "view" | "perspective" | "layout"
  term_id: str
  evidence: list[str] (one or more original excerpts; source_job_id=null means current request)
  confidence: float (0.0 <= confidence <= 1.0)
  source_job_id: UUID | null
```

- `select_terms`: selections는 한 개 이상, 역할 중복 없음, `unresolved_constraints=[]`, `clarifying_question=null`, `clarification_type=null`. `evidence`는 현재 요청 또는 `source_job_id`가 가리키는 동일 대화의 선행 원본 요청·카드 라벨의 실제 표현을 하나 이상 인용한다. resolver는 지정된 원본과 대조한다.
- `needs_clarification`: `selections=[]`, `unresolved_constraints`는 비어 있거나 공백만으로 이루어지지 않은 항목을 한 개 이상, `clarifying_question`은 시각 단서를 묻는 짧은 한국어 질문 하나, `clarification_type`은 비어 있지 않은 enum 하나다. 사람에게 읽히는 출력은 한국어로 작성하고 evidence는 원본 인용 표기를 보존한다. LLM의 질문은 구조 검증용이며 API 응답에는 전달되지 않고 resolver가 고정 질문으로 교체한다.
- Prompt는 최종 `agent_status`, `reason_codes`, Pinterest 검색어·URL·MCP 호출·카드 설명을 만들지 않는다. Pydantic 검증과 resolver가 이를 각각 조립·검증하고, resolver는 evidence가 허용된 현재 또는 동일 대화의 원본에 실제로 있는지 재검증한다.
- `clarification_type`은 최종 `reason_code`가 아니다. resolver는 입력 단서와 카드 `confidence_gate`, 카탈로그 의존 그래프를 다시 확인한 뒤에만 `ABSTRACT_INTENT_ONLY`, `INSUFFICIENT_VISUAL_EVIDENCE`, `CONFLICTING_CONSTRAINTS` 중 최종 코드를 조립한다. `requires_*`의 부모 ID가 selection에 없다는 사실만으로 후보를 실패시키지 않는다. 직접 검색 금지는 LLM 출력과 무관하게 `DIRECT_SEARCH_DISABLED`로 처리한다.
- 해결되지 않은 모호성은 새 사용자 메시지의 새 job에서 다시 `needs_clarification`으로 처리한다. `pending_human_review`는 현재 공개 API와 `InterpretationOutput`의 enum이 아니다.
- 구조적으로 유효해도 활성 카드·역할·카탈로그 의존 그래프 검증은 반드시 코드가 다시 수행한다.

## AC

**AC-01 · 허용 카드만 선택**
- GIVEN: `active_cards_json`과 카드 밖 용어를 요구하는 입력이 있다.
- WHEN: Prompt가 `select_terms`를 반환한다.
- THEN: 모든 `term_id`는 `active_cards_json`에 존재하고 각 `role`과 일치한다.

**AC-02 · 실제 단서 근거**
- GIVEN: 정상 사용자 요청과 활성 카드가 있다.
- WHEN: Prompt가 selection을 반환한다.
- THEN: 각 `evidence`는 현재 요청 또는 지정된 선행 원본의 실제 단서이며, 질문·안내는 한국어이고, 역할은 중복되지 않고 정해진 순서를 따른다.

**AC-03 · 모호·상충 입력**
- GIVEN: 카드 confidence gate를 만족하지 못하거나 서로 충돌하는 단서가 있다.
- WHEN: Prompt가 해석한다.
- THEN: `needs_clarification`, 해당 `clarification_type`, 빈 selections, 한 개의 쉬운 한국어 질문을 반환한다.

**AC-04 · 책임 경계**
- GIVEN: Prompt가 어떤 입력을 처리한다.
- WHEN: JSON을 반환한다.
- THEN: 최종 API 상태·사유 코드·검색어·URL·도구 호출·카드 설명을 포함하지 않는다.

**AC-05 · 구조화 출력 실패**
- GIVEN: LLM 출력이 JSON 또는 Pydantic 계약을 위반한다.
- WHEN: LLM adapter가 검증한다.
- THEN: 해당 출력은 resolver·검색 provider에 전달되지 않고 API 계약의 재시도·실패 정책을 따른다.

**AC-06 · 한 개의 System message와 후속 질문**

- GIVEN: v0 해석 요청과 해결되지 않은 모호성이 있다.
- WHEN: adapter와 resolver가 처리한다.
- THEN: 영어 v0 System message 하나만 LLM에 전달하고, resolver는 새 term ID·`pending_human_review` 없이 새 job의 `needs_clarification`으로 처리한다.

## 대화 맥락 확장

source_job_id(nullable UUID)와 context_updates(role, term_id nullable, evidence)를 추가한다. 현재 조건/미해결 질문/최근 6개/요약/원본 출처는 서버만 구성한다. 현재 요청의 명시적 수정만 조건을 갱신하고 추천을 사용자 사실로 승격하지 않는다. 원본 근거 검증은 conversation-context.md를 따른다. 동일 파일의 Memory classify/summarize/answer 절은 각각 검색 조건·요약·기록 기반 회상 답변만 생성하며, 외부 지식과 검색 URL을 생성하지 않는다.
