# 결정론 범위 밖 요청 gate

## Why

- 페르소나: 텍스트 기반 캐릭터 레퍼런스를 찾는 사용자.
- 상황: 이미지 생성·업로드 이미지 분석·작가 화풍 복제·Pinterest 대량 수집 요청도 현재 해석 prompt로 전달되며, prompt가 서버 enum에 없는 상태를 출력하도록 요구한다.
- 문제: 해당 응답은 구조 검증에 실패하거나 지원하지 않는 동작을 레퍼런스 검색으로 오인하게 한다.
- 측정 지표: EVAL-17~20이 `out_of_scope`로 완료되고 LLM·resolver·검색 호출은 0회다.

## Goal

- 명시된 미지원 작업을 결정론적으로 분류하고 API가 이미 정의한 `AgentStatus.OUT_OF_SCOPE` 결과를 반환한다.
- unsafe-input gate 우선순위를 유지한다.
- Out of Scope: 임의의 도메인 분류기, 모델 기반 범위 판정, `InterpretationState` enum 확장, 프롬프트·resolver의 새 범위 상태.

## What

- gate는 이미지 생성·편집, 업로드/첨부 이미지 분석, 특정 현존 작가의 화풍 복제, Pinterest 핀 대량 수집·다운로드·저장 요청을 처리한다.
- 미지원 작업이 명시적으로 요청된 긍정 작업일 때만 gate가 작동한다. 부정하거나 필요 없다고 한 작업의 언급은 범위 밖 근거가 아니다.
- 긍정 미지원 작업과 레퍼런스 검색 단서가 함께 있으면 미지원 작업이 우선해 범위 밖으로 종결한다. 미지원 작업이 부정되고 별도의 텍스트 레퍼런스 검색 요청이 남으면 gate를 통과시켜 지원되는 시각 단서만 해석한다.
- 안전하지 않은 요청은 먼저 기존 unsafe gate에서 종결된다.
- 범위 밖이면 job은 `completed` 상태와 `agent_status=out_of_scope`, `reason_codes=[OUT_OF_SCOPE_REQUEST]`로 종결되고 `reference_plan`과 `clarifying_question`은 null이다.
- 범위 밖 입력은 대화 메모리, LLM, resolver, 검색에 전달하지 않는다.
- 지원 여부가 불명확한 입력은 이 gate에서 추측하지 않고 기존 LLM 해석 계약에 남긴다.

## How

- `backend/services/input_safety.py`의 동일 입력 정규화 결과에 대해 별도 `is_out_of_scope_input()` 함수를 제공한다.
- `AgentJobWorker._process_claimed()`는 VALIDATING 전환 후 unsafe 검사, 범위 밖 검사, 대화 메모리·LLM 순서로 실행한다.
- 범위 판정은 문장 구두점으로 끊긴 뒤 수행해 한 문장에 언급한 `Pinterest`가 뒤 문장의 부정된 다운로드·저장 요청과 결합되지 않게 한다.
- 미지원 작업 직후의 `말고`, `없이`도 부정 표현으로 처리한다. 부정은 해당 작업에만 적용하며 다른 긍정 미지원 작업이 남으면 범위 밖으로 종결한다.
- 최종 결과는 서버가 상수 상태·사유 코드와 고정 안내문으로 조립한다.
- v2-v4 프롬프트에는 범위 밖 `InterpretationState` 출력 규칙을 두지 않는다. 해당 enum은 `select_terms`와 `needs_clarification`만 허용한다.

## AC

- GIVEN: EVAL-21 또는 EVAL-22 WHEN: worker gate를 평가 THEN: `unsafe_input`으로 종결하고 범위 밖 gate를 실행하지 않는다.
- GIVEN: EVAL-17~20 WHEN: worker gate를 평가 THEN: `out_of_scope`와 `OUT_OF_SCOPE_REQUEST`로 종결하고 adapter·resolver·검색을 호출하지 않는다.
- GIVEN: 명시된 텍스트 기반 캐릭터 체형·포즈·시점 요청 WHEN: worker가 gate를 적용 THEN: gate를 통과해 기존 해석 흐름으로 진행한다.
- GIVEN: 미지원 작업을 부정하고 별도 레퍼런스 검색을 요청 WHEN: worker가 gate를 적용 THEN: gate를 통과하고 supported clue만 해석한다.
- GIVEN: `이미지 생성 말고` 또는 `이미지 생성 없이` 마른 체형 레퍼런스를 요청 WHEN: gate를 적용 THEN: 두 입력과 기존 정상 요청 3건은 통과한다.
- GIVEN: 이미지 생성을 `말고` 또는 `없이`로 부정하지만 업로드 분석이나 이미지 편집도 별도로 요청 WHEN: gate를 적용 THEN: 남은 긍정 미지원 작업으로 차단한다.
- GIVEN: 긍정 미지원 작업에 레퍼런스라는 단어가 함께 있음 WHEN: worker가 gate를 적용 THEN: 범위 밖으로 종결한다.
- GIVEN: EVAL-17~20 WHEN: 부정·구두점이 반영된 gate 회귀를 실행 THEN: 네 요청은 범위 밖으로 판정한다.
- GIVEN: v2-v4 후보 프롬프트 WHEN: JSON 출력 계약을 따른다 THEN: `out_of_scope`를 `interpretation_state`로 출력하지 않는다.
