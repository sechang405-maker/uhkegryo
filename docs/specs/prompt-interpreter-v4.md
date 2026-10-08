# 해석 프롬프트 v4 회귀 보완

## Why

- 페르소나: 새 레퍼런스를 요청하거나 이전 조건을 수정하는 사용자.
- 상황: v3 전체 평가 22/30에서 범위 밖·후속 요청·카드 경계 회귀가 나타났다.
- 문제: 새 요청을 기억 회상으로 오인하거나, 한쪽 다리 체중만으로 콘트라포스토를 선택한다.
- 측정 지표: 같은 30문항 기대값 일치, 기존 통과 문항 회귀 수, 호출·비용·지연.

## Goal

- 새 검색 요청·회상 질문·범위 밖 요청을 구분한다.
- 체중 이동과 콘트라포스토, 옆모습과 정면 단서를 구분한다.
- Out of Scope: 평가 기대값 변경, 카드 데이터 변경, 모델 기본값 변경.
- 해석 provider 호출은 job attempt당 한 번이며, 기존 `JobRetryRecovery`가 최초 호출 포함 최대 세 attempt를 관리한다.
- 구조화 출력 검증 실패는 해당 attempt를 실패 처리하고, 내부 교정 재호출은 하지 않는다.
- 사용자 원문이나 모델 출력에서 추출한 값은 system 메시지로 전달하지 않는다.
- 모델 해석 상태는 `select_terms`와 `needs_clarification`만 허용한다. 범위 밖 판정은 서버가 처리한다.

## What

- `다시 찾아 줘`는 새 검색이며 `전에 무엇을 추천했어?`는 회상이다.
- 이미지 생성·편집, 업로드 이미지 분석, 작가 화풍 복제, Pinterest 대량 수집 등 명시된 미지원 작업을 긍정적으로 요청하면 worker gate가 전체를 범위 밖으로 처리한다. 레퍼런스 단서가 함께 있어도 미지원 작업이 우선한다.
- 미지원 작업을 부정하거나 필요 없다고 명시하고 별도 레퍼런스를 요청하면 gate를 통과해 시각 단서만 해석한다. `하지 말고`, `말고`, `없이`, `필요 없어`는 해당 작업에만 적용하며 다른 긍정 미지원 작업이 남으면 차단한다.
- 한국어 `올린/첨부한 그림을 분석·판정` 표현도 새 레퍼런스 탐색으로 오인하지 않는다.
- 한쪽 다리에 체중을 싣는 단서만 있으면 `pose_weight_shift`; 어깨·골반의 반대 기울기까지 있어야 `pose_contrapposto`다.
- 어깨와 골반이 같은 쪽으로 기울어도 명시된 한쪽 다리 체중 지지는 `pose_weight_shift` 근거로 유지한다.
- 옆모습과 정면의 양쪽 눈·귀가 동시에 선명해야 한다는 요청은 상충 조건으로 질문한다.
- 각 역할을 최종 출력 전에 중복 검사한다.
- 앉은 상태에서 손을 뻗는 요청은 기본 포즈 `pose_sitting` 하나를 선택하고 손의 크기 효과는 `perspective_foreshortening`으로 분리한다.
- 단순히 아래에서 올려다본다는 표현은 `view_low_angle`; `view_worms_eye`는 개미 눈높이 또는 지면 바로 근처 시점이 명시된 경우에만 선택한다.

## How

- 모호·상충 조건의 대조 규칙, 다음 attempt 검증 피드백, 통합 답변·관찰 지점과 실제 최종 질문 평가의 최신 계약은 [ambiguity-answer-quality.md](ambiguity-answer-quality.md)를 따른다.

- 복합 동작의 방향·흐름 자체를 찾으면 `pose_gesture`를 검토하고 개별 동작 카드를 같은 역할로 나열하지 않는다. 실제 지지·자세가 중심이면 해당 자세 카드 하나를 선택한다.
- 의상 부피만으로 체형을 판단할 수 없으면 `needs_clarification`의 모든 필드를 일관되게 출력한다.
- 근거는 카탈로그의 설명이 아닌 허용된 요청 원문에서 복사하며, 후속 요청의 `selections`와 `context_updates` 모두 동일한 인용 규칙을 적용한다.
- 2026-10-02 보완은 `openai/gpt-4.1-mini`로 EVAL-06/13/27만 재평가한다. 전체 통과율은 이번 부분 평가에서 계산하지 않는다.

- v3 프롬프트의 해석 규칙과 `Memory classify` 규칙을 보강한다.
- 동일 `gpt-4.1-mini`와 동일 평가셋으로 실패 8건과 전체 30건을 순서대로 실행한다.
- full run 결과가 기준보다 나쁘거나 중대한 회귀가 있으면 기본 설정에 적용하지 않는다.

## AC

- GIVEN: 달리며 방향을 바꾸는 동세와 아래 시점 요청 WHEN: 해석 THEN: `pose_gesture`와 `view_low_angle`을 역할당 하나씩 선택한다.
- GIVEN: 의상 때문에 넓어 보이는 어깨만 명시 WHEN: 해석 THEN: `insufficient_visual_evidence` 질문이며 선택과 검색 계획이 없다.
- GIVEN: 체형을 유지하고 한쪽 다리로 체중을 옮기는 후속 요청 WHEN: 해석 THEN: `pose_weight_shift`를 선택하고 모든 현재 근거는 요청의 연속 부분 문자열이다.

- GIVEN: 새 레퍼런스 검색·수정 요청 WHEN: memory classify THEN: `mode=none`이다.
- GIVEN: 과거 추천 내용을 묻는 요청 WHEN: memory classify THEN: `mode=recall`이다.
- GIVEN: 긍정 미지원 작업과 레퍼런스 단서가 함께 있음 WHEN: worker gate 적용 THEN: 전체를 `out_of_scope`로 완료하고 LLM·검색을 호출하지 않는다.
- GIVEN: 이미지 생성·업로드 분석을 부정하고 별도 레퍼런스를 요청 WHEN: worker gate 적용 THEN: 정상 해석 흐름을 탄다.
- GIVEN: 한 미지원 작업은 부정하지만 다른 긍정 미지원 작업이 남음 WHEN: worker gate 적용 THEN: 범위 밖으로 종결한다.
- GIVEN: 한쪽 다리 체중만 명시 WHEN: 해석 THEN: `pose_weight_shift`이고 콘트라포스토는 선택하지 않는다.
- GIVEN: 옆모습과 정면 단서가 충돌 WHEN: 해석 THEN: `conflicting_constraints` 질문이다.
- GIVEN: 고정 30문항 WHEN: v4 평가 THEN: 문항별 회귀와 비용·지연을 기록한다.
- GIVEN: 구조화된 해석 응답이 검증에 실패 WHEN: 한 job attempt를 실행 THEN: provider 호출은 1회이며 실패는 worker attempt 재시도 정책에 전달된다.
- GIVEN: 해석 검증 피드백을 구성 WHEN: adapter system message를 작성 THEN: 메시지에는 고정 규칙만 있고 요청 원문·이전 출력·후보 ID는 없다.
- GIVEN: v4 프롬프트 상태 계약 WHEN: enum과 대조 THEN: `select_terms`와 `needs_clarification`만 모델 출력 상태다.
- GIVEN: 평가 재현 runner가 브랜치에 없거나 실행 metadata가 dirty 상태다 WHEN: 30문항 결과를 보고 THEN: 해당 결과를 PR head의 재현 결과로 표시하지 않고 검증 불가 상태와 실제 commit을 기록한다.
