# 해석 프롬프트 v2 평가

## Why

- 페르소나: 그림 레퍼런스를 요청하는 초보 사용자.
- 상황: 실제 모델 30문항 평가에서 17건만 고정 기대값과 일치했다.
- 문제: 근거를 의역하거나 같은 역할의 카드를 중복 선택해 3회 재시도 후 실패한다.
- 측정 지표: 고정 30문항 기대값 일치, 구조화 출력 실패 건수, 호출 수, p95 지연.

## Goal

- `uhkegryo-interpreter-v2` 후보를 만들고 기존 v0·v1과 동일 모델·평가셋으로 비교한다.
- 원문 근거, 역할당 하나의 선택, 불충분·상충 단서 처리 규칙을 강화한다.
- Out of Scope: 활성 카드 수정, resolver 검증 완화, 모델 변경, Langfuse production label 변경.

## What

- 근거는 `<request_text>` 또는 검증된 선행 원본의 연속된 정확한 부분 문자열로 복사한다.
- 긴 카드 목록 뒤에 요청 원문을 다시 제시해 인용할 문자열이 출력 지시 바로 앞에 오게 한다.
- 각 역할은 최대 하나만 선택하고, 앉은 자세와 손의 원근 효과처럼 다른 역할의 단서를 혼동하지 않는다.
- 명시적 기대어 누운 자세는 일반 바닥 지지보다 구체적인 자세 카드로 판정한다.
- 단서가 부족하거나 한 역할에서 상충하면 추측 대신 질문한다.
- 기존 JSON 필드, enum, 활성 카드 제한은 유지한다.

## How

- `prompts/uhkegryo-interpreter-v1.md`를 복사해 v2를 만들고 규칙과 예시만 보강한다.
- 후보 평가는 `INTERPRETER_PROMPT_PATH`와 `INTERPRETER_PROMPT_VERSION`을 v2로 지정한다.
- 첫 비교는 EVAL-04·08·10·14·15·28, 최종 비교는 전체 30문항을 사용한다.

## AC

- GIVEN: 요청의 근거 문구가 있다. WHEN: 해석한다. THEN: evidence와 context update 근거는 실제 원문의 연속 부분 문자열이다.
- GIVEN: 한 요청에 앉음과 손의 원근 효과가 있다. WHEN: 해석한다. THEN: pose는 하나만 선택하고 원근 단서는 perspective 역할로 분리한다.
- GIVEN: 바닥에 기대어 누운 자세가 명시됐다. WHEN: 해석한다. THEN: `pose_reclining`을 우선한다.
- GIVEN: 상충하는 체형 또는 시점 조건이 있다. WHEN: 해석한다. THEN: 선택 없이 질문하고 `conflicting_constraints`를 반환한다.
- GIVEN: 같은 30문항과 모델을 사용한다. WHEN: v2를 평가한다. THEN: 문항별 회귀와 호출 수를 기록한다.
