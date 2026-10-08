# 일부 역할 이미지 교체
## Why
사용자는 체형·포즈 이미지를 유지하며 나머지 시점 이미지만 바꾸고 싶다. 요청하지 않은 역할의 검색 0건과 Pin 보존이 지표다.
## Goal
같은 카드 조건에서 지정한 역할의 이미지만 교체한다. 자유 검색어·새 UI·배포는 제외한다.
## What
- '체형·포즈 조건은 유지하고 모든 참고 이미지를 새로 찾아줘'는 refresh_all이다.
- '체형·포즈 이미지는 그대로 두고 나머지만 다른 레퍼런스로 찾아줘'는 현재 보드의 나머지 역할만 refresh_roles다. 세 역할이면 view만 대상이다.
- '시점 이미지만 새로 찾아줘'도 refresh_roles=[view]다. '포즈를 앉은 자세로 바꿔줘'는 조건 변경인 update다.
- 교체 역할이 없거나 이전 보드에 없거나 비활성·검색 금지이면 확인 질문을 반환한다. 나머지가 없는 요청은 질문하며 전체 교체로 확대하지 않는다.
## How
- RecallQuery.reference_action에 refresh_roles를 추가하고 refresh_roles: list[Role](최대 5개, 기본 [])를 추가한다. 중복은 거부한다. update/refresh_all의 역할 목록은 []만 허용한다.
- classify 입력에는 서버의 current_reference_roles 목록만 추가한다. '나머지'의 대상은 이 목록에서 이미지 유지 역할을 제외한 역할이다. 식별 못하면 빈 refresh_roles를 반환해 서버가 질문한다.
- refresh_roles는 선택된 이전 카드를 그대로 검색한다. LLM 카드 재해석·조건 갱신은 하지 않는다. refresh_all과 동일하게 직전 보드 전체 Pin ID를 제외해 다른 역할의 기존 이미지도 새 결과로 재사용하지 않는다.
- 새/다른 이미지 요청의 classify 빠른 경로 생략은 차단한다. refresh_roles 목록은 서버가 현재 보드의 활성 카드에 대조한 후 사용한다.
- 비대상 카드의 결과는 병합해 그대로 유지한다. reference_update는 reference-update-metadata.md를 따른다. 실패·빈 결과는 대상 역할만 빈 결과로 교체한다.
## AC
- Given body/pose/view 보드, When 체형·포즈 이미지는 유지하고 나머지 교체, Then view만 같은 카드로 검색하고 body/pose Pin을 보존하며 metadata도 view 교체다.
- Given 일부 역할 교체, When 기존 Pin만 반환, Then 대상 역할은 빈 결과와 안내이며 나머지 Pin은 보존된다.
- Given 빈 범위·없는 역할·비활성 카드·보드 없음, When 일부 교체, Then 검색 없이 질문하며 모든 기존 역할을 유지한다.
- Given 분류 프롬프트, When 조건 유지 전체 교체/이미지 유지 부분 교체/조건 변경 예시, Then 서로 다른 action과 범위 규칙 및 서버 역할 목록이 전달된다.

검증(2026-10-07): 원래 로컬 수용 기준 27개, PR 작업 폴더 전체 backend 647개, frontend 55개 통과. 실제 PostgreSQL 16에서 부분 교체·확인 질문 메타데이터의 저장·재조회를 확인했다. LLM·검색은 fixture로 대체했다.
