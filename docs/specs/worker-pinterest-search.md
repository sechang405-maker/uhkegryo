# Worker Pinterest 검색 단계 연결 (작업 13)

## Why

- **페르소나**: 그림 레퍼런스를 찾는 사용자.
- **상황**: Worker가 LLM 후보를 resolver로 검증하고도 현재 Pinterest 검색 결과 없이 Job을 완료한다.
- **문제**: 결과에 실제 Pin과 검색 장애 사유가 없어 UI가 참고 자료를 보여 주지 못한다.
- **측정 지표**: 검증된 검색 가능 카드가 결과로 선택되면 각 역할 검색 결과와 reason code가 완료 Job에 반영된다.

## Goal

- resolver 검증 뒤 LLM이 등록 MCP 도구 중 필요한 도구를 선택하고 worker가 안전하게 중계한다. Pinterest 검색 인자는 승인 TERM_CARD의 `query_fragments`로 제한한다.
- provider 결과를 `RoleSearchOutcome`으로 모아 response assembler에 전달한다.
- 검색 장애 결과는 역할별 최대 3회 조회하며, 최종 장애는 `PIN_SEARCH_UNAVAILABLE`, 정상 빈 결과는 `PIN_RESULTS_EMPTY`로 구분한다.
- 모든 승인 역할의 검색 호출이 없으면 도구 선택 실패로 처리하고, `PIN_SEARCH_UNAVAILABLE`로 위장하지 않는다. MCP 설정 오류는 `CONFIGURATION_ERROR`로 보존한다.
- **범위 밖**: Pinterest 공개 검색·Widget 구현 변경, LLM 재시도 정책 변경, 실패 코드 공개 문구 변경(작업 15), UI 구현.

## What

1. Worker가 `searching` 상태로 전환한 뒤 MCP `tools/list`의 도구 명세와 resolver 승인 term을 LLM에 제공한다. LLM이 선택한 검색 호출은 해당 역할과 카드의 `query_fragments`가 정확히 일치할 때 MCP로 전달한다.
2. 성공한 검색의 Pin과 정상 빈 검색 결과를 각각 MCP 결과에서 보존한다. `PIN_RESULTS_EMPTY`는 재조회하지 않는다.
3. `PIN_SEARCH_UNAVAILABLE`이면 LLM이 같은 승인 역할·조각으로 검색 도구를 다시 선택하게 해 총 3회까지 시도하고 첫 번째·두 번째 장애 뒤 각각 1초·2초 기다린다. 이후에도 실패하면 해당 역할의 마지막 unavailable 결과를 유지하고 다른 역할 검색을 계속한다.
4. 역할별 결과를 response assembler에 전달한다. 다른 역할에 결과가 있으면 결과는 `partial_result`가 되며 unavailable 역할의 Pin 목록은 비어 있다. 모든 역할의 정상 빈 검색은 `PIN_RESULTS_EMPTY`를 집계한다.
5. clarification 또는 유효한 검색 카드가 없는 결과는 Pinterest provider를 호출하지 않는다. 직접 검색 금지 카드도 resolver가 유효 검색 대상으로 전달하지 않는다.
6. MCP 도구 결과는 원래 `tool_call_id`로 LLM에 반환한다. 검색 도구 호출 실패는 역할별 재시도에 포함하고, 설정 오류는 `CONFIGURATION_ERROR`로 보존한다. LLM이 다른 도구만 호출하거나 호출을 멈춰 승인 검색 역할이 남으면 `LLM_INVALID_STRUCTURED_OUTPUT`으로 Job을 실패 처리한다.
7. 승인되지 않은 검색 조각은 MCP에 전달하지 않고 도구 오류로 LLM에 돌려준다. 올바른 검색 호출로 회복할 수 있으며, 잘못된 인자는 검색 장애 횟수에 포함하지 않는다.

## How

- Worker는 [공통 MCP 도구 gateway](./mcp-contract.md)를 사용해 등록 도구 명세를 LLM에 전달하고, 모델이 선택한 도구 호출을 실행한다. 검색은 기존 MCP 결과 계약과 widget 경로를 유지한다.
- 승인 검색 대상은 resolver가 반환한 카드 순서를 따른다. worker 검증 쌍은 `ValidatedTerm.selection.role` 및 `tuple(ValidatedTerm.card["query_fragments"])`다. LLM 원문이나 추가 free-text를 검색 인자로 사용하지 않는다.
- 역할당 최대 검색 호출은 3회다. retryable outcome은 `code == ReasonCode.PIN_SEARCH_UNAVAILABLE`일 때뿐이며 backoff는 호출 후 1,000ms, 2,000ms다. `PIN_RESULTS_EMPTY` 및 Pin별 Widget 접근 불가(`deleted`)는 재시도하지 않는다.
- `run_once(search_outcomes=...)`에 결과가 직접 주어진 경우 테스트 seam을 유지하고 MCP 도구를 호출하지 않는다.
- 검색 outcome의 조립과 공개 reason code는 기존 `assemble` 및 `RoleSearchOutcome` 계약을 재사용한다. 썸네일 비저장 규칙은 작업 12를 따른다.
- 동일 LLM 응답의 독립 역할 검색은 [병렬 검색 Spec](./parallel-role-search.md)에 따라 worker 공유 한도 3개로 실행한다. 검색 외 도구는 순서 경계를 유지하고, 동일 응답의 중복 역할은 첫 유효 호출만 실행한다. 결과는 원래 호출 순서와 `tool_call_id`로 반환한다.

## AC

**AC-01 · 유효 카드 검색 호출**

- GIVEN: resolver가 검색 가능한 카드 하나 이상을 승인한다.
- WHEN: Worker가 `searching` 단계에 진입한다.
- THEN: LLM이 승인된 역할·조각으로 검색 MCP 도구를 선택할 수 있고, 그 결과를 완료 payload에 반영한다.

**AC-02 · 빈 결과와 검색 장애 구분**

- GIVEN: MCP 검색 도구가 한 역할에 `PIN_RESULTS_EMPTY`, 다른 역할에 `PIN_SEARCH_UNAVAILABLE`을 반환한다.
- WHEN: Worker가 역할 결과를 조립한다.
- THEN: 빈 결과는 재시도 없이 `PIN_RESULTS_EMPTY`로 남고, unavailable 결과는 최대 세 번 MCP 호출 후 `PIN_SEARCH_UNAVAILABLE`로 남는다.
- AND THEN: 두 reason code는 TermResult와 AgentResult에 계약대로 집계된다.

**AC-03 · 부분 검색 성공**

- GIVEN: 한 역할 검색은 성공하고 다른 역할 검색은 세 번 모두 unavailable이다.
- WHEN: Worker가 Job을 조립한다.
- THEN: 성공한 Pin을 유지하고 장애 역할에는 빈 pins와 `PIN_SEARCH_UNAVAILABLE`을 넣어 `partial_result`를 완료한다.

**AC-04 · 검색 불필요 상태**

- GIVEN: resolver가 clarification 결과 또는 검색 가능한 카드를 하나도 승인하지 않는다.
- WHEN: Worker가 Job을 처리한다.
- THEN: MCP 도구 목록을 LLM에 제공하거나 Pinterest 검색 도구를 호출하지 않는다.

**AC-05 · 미검색 역할과 설정 오류 구분**

- GIVEN: LLM이 승인 역할의 검색 도구를 호출하지 않거나 MCP가 `CONFIGURATION_ERROR`를 반환한다.
- WHEN: Worker가 MCP 도구 선택·실행을 마친다.
- THEN: 미검색 역할은 `LLM_INVALID_STRUCTURED_OUTPUT`로 처리하고, 설정 오류는 `CONFIGURATION_ERROR`로 보존한다. 두 경우 모두 `PIN_SEARCH_UNAVAILABLE`로 완료하지 않는다.

**AC-06 · 잘못된 검색 인자 복구**

- GIVEN: LLM이 승인되지 않은 검색 조각을 호출한 뒤 승인된 조각으로 다시 호출한다.
- WHEN: Worker가 두 도구 호출을 처리한다.
- THEN: 첫 호출은 MCP 검색 없이 도구 오류를 반환하고, 검색 시도로 집계하지 않으며, 두 번째 유효 호출 결과를 사용한다.
