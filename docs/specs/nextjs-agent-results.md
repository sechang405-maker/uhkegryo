# Next.js Agent 결과와 레퍼런스 표시

## Why

- **페르소나**: 용어가 낯선 캐릭터 일러스트 초보 사용자
- **상황**: 비동기 요청이 완료되면 해석 답변과 역할별 Pin 레퍼런스를 확인한다.
- **문제**: 답변 상태와 이미지 검색 상태가 섞이면 사용자가 해석 결과와 검색 실패를 구분하기 어렵다.
- **측정 지표**: 완료 응답의 상태별 안내 표시율 100%, 표시 가능한 Pin의 원본 링크 제공률 100%.

## Goal

- 대화 영역에 완료 답변을 표시하고, `success`·`partial_result`의 역할별 레퍼런스를 갤러리에 제공한다.
- 질문·실패·안전 거절·범위 밖 응답을 각각의 안내 흐름으로 표시한다.
- 이미지 검색 실패가 통합 답변이나 다른 역할의 결과를 가리지 않게 한다.
- **범위 밖**: 이미지 저장·프록시, 기존 Job 재시도 API, 별도 Pin 이력 저장소.

## What

1. 대화에는 사용자 요청과 Job 완료 답변을 순서대로 표시한다. 답변 문자열은 허용된 Markdown 요소만 렌더링한다.
2. `success`와 `partial_result`의 `reference_plan.terms`는 역할별 갤러리로 표시한다. 검색 가능한 Pin 썸네일을 선택하면 미리보기를 열고, 원본 Pin 링크를 제공한다.
3. `PIN_RESULTS_EMPTY`와 `PIN_SEARCH_UNAVAILABLE`은 해당 역할의 갤러리에서 각각 결과 없음과 검색 실패로 안내한다. 검색 재시도는 해당 역할의 용어 검색으로 수행한다.
4. `needs_clarification`은 질문과 직접 입력 경로를 제공한다. API에 선택지가 포함된 경우에만 선택지를 입력창에 채우며, 자동 전송하지 않는다.
5. `out_of_scope`, `unsafe_input`, Job `failed`는 안전한 사용자 안내를 표시한다. Job 실패 재시도는 원래 요청을 입력창에 복원하고 사용자가 다시 전송한다.

## How

- 완료 답변은 `job.result.answer_text`를 사용한다. 확인 질문은 `clarifying_question`, 안전·범위 거절은 `user_message`, Job 실패는 `failure.user_message`를 우선 표시한다. 계약은 [API Spec](./api-contract.md)과 [통합 답변 Markdown 표시 Spec](./markdown-answer-rendering.md)을 따른다.
- 레퍼런스는 완료 상태의 `success` 또는 `partial_result`만 표시한다. 역할·용어·Pin 순서는 서버 응답을 따른다. `available`이며 `thumbnail_url`이 있는 Pin만 이미지를 표시한다. 원본은 응답의 `pin_url`을 사용한다.
- `thumbnail_url`과 이미지 바이트는 영구 저장하지 않는다. 접근할 수 없는 Pin은 이미지 대신 안내를 표시한다. 보관 경계는 [Pinterest Widget 결과 Spec](./pinterest-widget-results.md)을 따른다.
- 기존 대화 이력, 갤러리 탐색, 용어 검색, 로딩과 이미지 미리보기 동작은 각각의 Studio Spec을 따른다. 이 문서는 API 계약을 변경하지 않는다.

## AC

**AC-01 · 완료 답변과 역할 갤러리**

- GIVEN: 완료된 `success` 또는 `partial_result` 응답과 역할별 결과가 있다.
- WHEN: 대화와 레퍼런스 영역을 표시한다.
- THEN: 답변을 안전한 Markdown으로 표시하고, 응답 순서에 따라 역할별 용어와 Pin을 보여 준다.

**AC-02 · Pin 미리보기와 출처**

- GIVEN: Pin 상태가 `available`이고 `thumbnail_url`이 있다.
- WHEN: 사용자가 갤러리 이미지를 선택한다.
- THEN: 썸네일 미리보기를 표시하고 `pin_url`로 원본을 열 수 있다.
- GIVEN: Pin을 사용할 수 없거나 썸네일 URL이 없다.
- WHEN: 갤러리를 표시한다.
- THEN: 접근 불가 안내를 표시하며 썸네일을 보관하지 않는다.

**AC-03 · 부분 검색 실패**

- GIVEN: `partial_result`에서 한 역할의 검색이 비었거나 실패했다.
- WHEN: 레퍼런스를 표시한다.
- THEN: 해당 역할의 원인을 안내하고 용어 검색을 다시 할 수 있으며, 다른 역할의 결과와 통합 답변은 유지한다.

**AC-04 · 질문과 실패 처리**

- GIVEN: `needs_clarification`, 거절 상태 또는 Job `failed` 응답이 있다.
- WHEN: 대화 답변을 표시한다.
- THEN: 상태에 맞는 사용자 안내를 표시하고, 질문 선택지는 API에 존재할 때만 입력창을 채우며 자동 전송하지 않는다.
