# 조건을 유지한 전체 레퍼런스 교체

## Why
사용자는 현재 체형·포즈에 만족하지만 다른 참고 이미지를 보고 싶다. 같은 Pin 재출력 없이 현재 조건을 보존하는 것이 성공 지표다.

## Goal
전체 새 레퍼런스 요청에서 현재 카드 조건은 유지하고 기존 Pin을 제외해 재검색한다. 검색 결과를 조작하거나 반드시 8개 새 이미지를 보장하는 기능은 제외한다.

## What
- '체형·포즈 조건은 유지하고 모든 참고 이미지를 새로 찾아줘'는 현재 보드 전체 교체다. 이미지 자체를 유지하고 나머지만 교체하는 요청은 reference-role-refresh.md를 따른다.
- '포즈만 앉은 모습으로 바꿔줘'는 전체 교체가 아니라 selective-reference-update.md를 따른다.
- 이전 레퍼런스가 없거나 현재 카드가 비활성/검색 금지이면 조건을 먼저 확인하는 질문을 반환한다.
- 새 Pin이 없으면 기존 Pin을 새 결과인 것처럼 재사용하지 않고 빈 결과와 안내를 반환한다. 검색 장애는 기존 장애 코드를 사용한다.

## How
- RecallQuery의 reference_action은 update|refresh_all|refresh_roles(기본 update)다. 명시적인 전체 이미지 교체·조건 유지 요청만 refresh_all로 분류하며, 회상만 요청은 update다.
- refresh_all에서는 현재 session의 검증된 이전 reference_plan에서 카드를 재구성한다. 별도 카드 재해석과 context_updates 없이 같은 조건을 사용한다.
- MCP search_pinterest_pins에 선택적 exclude_pin_ids(nullable list, 최대 40개 숫자 문자열)를 추가한다. worker가 직전 보드의 모든 역할에서 Pin ID를 모아 중복 제거 후 각 검색에 주입한다. 역할이 달라져도 기존 이미지는 제외하며 LLM이 만든 제외 목록은 사용하지 않는다.
- provider는 Pinterest 단일 엔진의 검증된 검색 결과에서 제외 ID를 먼저 제거한 뒤 최대 8개를 선택한다. 남은 Pin이 없으면 PIN_RESULTS_EMPTY를 반환한다. 검색어와 카드 조각은 변경하지 않는다.
- 이전 보드가 있는 새/다른 레퍼런스 요청은 회상 분류를 생략하는 경로를 타지 않고 reference_action을 분류한다.
- worker에서도 반환 Pin의 제외 목록을 다시 검사한다. 제외 ID·썸네일은 모델 메시지와 trace에 넣지 않는다.
- 응답과 저장의 외부 Pin 경계, 세션 소유권·만료·선행 job 조건을 유지한다. 별도 캐시·DB migration은 없다.

## AC
- Given 현재 체형·포즈, When 전체 새 레퍼런스 요청, Then 같은 카드 ID로 두 역할을 검색하고 이전 Pin ID는 결과에 없다.
- Given 현재 체형·포즈·시점, When 전체 새 레퍼런스 요청, Then 세 역할의 카드 ID를 모두 유지하고 세 역할을 검색하며 기존 보드의 모든 Pin을 제외한다.
- Given 기존 Pin이 검색 결과 앞 8개와 일치하고 뒤에 새 Pin이 있음, When 검색, Then 제외 후 새 Pin을 반환한다.
- Given Pinterest 엔진에 이전 Pin만 있음, When 교체, Then PIN_RESULTS_EMPTY와 새 결과 없음 안내이며 기존 Pin은 반환하지 않는다.
- Given 이전 보드 없음/카드 비활성, When 전체 교체, Then 검색 없이 확인 질문을 반환한다.
- Given 연속 전체 교체, When 다음 job 실행, Then 직전 보드의 Pin을 제외하고 같은 카드 조건을 사용한다.
- Given 악의적인 LLM 제외 목록, When 도구 실행, Then 서버의 이전 Pin ID만 실제 제외 목록으로 전달한다.

검증: 2026-10-07 리뷰 대응 후 원래 로컬 수용 기준 27개 및 PR 작업 폴더 전체 backend 647개 통과(임시 PostgreSQL 16), frontend 55개 통과. 기존 로컬 Langfuse 작업은 PR 전체 검증에서 제외했다. 실제 LLM·외부 검색은 fixture로 대체했고 실제 서비스 연동은 미검증이다.
