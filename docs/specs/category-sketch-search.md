# 카테고리별 스케치 재검색

## Why
사용자가 같은 용어에서 스케치 위주의 레퍼런스를 찾아볼 수 있게 한다.

## Goal
각 결과 카테고리 제목 오른쪽에서 해당 카드만 재검색한다.
기존 검색 조각은 유지하고 마지막 접미사 drawing만 sketch로 바꾼다.
LLM·job·기록 저장은 하지 않는다.

## What
`일반 · 스케치 · 도형화`에서 스케치 선택 → 해당 행만 검색 중 → 성공 시 이미지와 검색어 갱신.
우측 대화와 다른 행은 변경하지 않는다. 적용 중인 모드는 강조 표시하며 재선택할 수 있다. 요청 중에만 해당 행의 버튼을 비활성화한다. 일반 재검색과 도움말은 category-search-modes.md를 따른다.
실패·빈 결과면 기존 이미지와 검색어를 유지하고 재시도 가능한 안내를 표시한다.
새 검색·홈·기록 이동은 진행 중 응답을 무시하고 재검색 상태를 초기화한다.
대화 더미 화면에서도 스케치 재검색은 실제 API를 호출한다. API가 실패하면 더미 이미지를 새 검색 결과라고 표시하지 않는다.

## How
POST /api/term-search 요청에 suffix: drawing|sketch|mannequinization(기본 drawing)를 사용한다. 도형화 검색은 category-mannequinization-search.md를 따른다.
서버 카탈로그 query_fragments는 변경하지 않는다. provider와 반환 search_url 모두 같은 suffix를 사용한다.
프론트는 term_id별 결과를 별도로 관리하고, 이미지·search_url만 대체한다.
해당 행이 활성일 때 상단 즉시 검색·복사에도 변경된 검색어를 적용한다.

## AC
- Given 5개 카테고리, When 포즈 재검색, Then 포즈에만 로딩·이미지 교체가 적용된다.
- Given 성공, When 활성 행 확인, Then 검색어는 sketch로 끝나고 설명은 그대로다.
- Given 실패 또는 빈 결과, When 응답 수신, Then 기존 이미지·검색어를 유지하고 재시도할 수 있다.
- Given 재검색 중, When 홈 이동, Then 늦은 응답이 화면을 변경하지 않는다.
- Given drawing 기본 요청, When 기존 API 실행, Then 기존 검색어를 유지한다.
