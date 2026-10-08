# Studio 프론트 검색 연결 경계

## Why
카드 클릭과 카테고리별 검색 모드 변경은 새로운 이미지를 받아야 한다.

## Goal
프론트의 요청·응답·실패 처리를 완성한다. 검색 공급자와 FastAPI 엔드포인트 구현은 이 PR에서 제외한다.

## What
POST /api/term-search에 term_id와 선택적 suffix를 보낸다. suffix는 drawing/sketch/mannequinization이다. 단일 카드 검색은 요청 기록이나 대화 turn을 추가하지 않는다. 재검색 성공 시 해당 행의 핀과 검색어만 교체한다. 실패 시 기존 이미지를 유지한다.

## How
팀 백엔드는 활성 카드를 조회해 TermResult를 반환해야 한다. 최소 term_id, role, pins, search_url, reason_codes와 카드 설명 필드가 필요하다. 각 Pin은 pin_id, pin_url, thumbnail_url, status를 제공한다. 실시간 공급자 동작이나 우회는 구현하지 않는다. 개발 더미의 홈 클릭은 fixture를 사용하지만 카테고리 재검색은 실제 API를 호출한다.

## AC
- Given 카드 클릭, When 실제 모드, Then /api/term-search만 호출하고 /api/agent는 호출하지 않는다.
- Given 검색 모드 변경, When 성공, Then 해당 카드의 검색어·핀만 교체한다.
- Given 잘못된 카드·HTTP 오류·썸네일 없음, When 응답, Then 성공으로 표시하지 않고 기존 재검색 결과를 유지한다.
- Given 같은 모드 재클릭, When 대기 중이 아님, Then 새 API 요청을 보낸다.
- Given 화면 전환·새 입력, When 이전 요청이 진행 중, Then 취소하고 늦은 응답을 반영하지 않는다.

## 백엔드 의존성
/api/term-search는 이 프론트 PR에 포함하지 않는다. 팀원 구현·별도 PR이 필요하다. 기존 Google/Pinterest 실험 코드는 게시하지 않으며 실제 공급자 변경에 따라 백엔드 계약을 맞춰야 한다.
