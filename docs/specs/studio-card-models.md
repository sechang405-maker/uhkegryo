# Studio 텀카드·결과 표시 모델

## Why
검수 완료 카드를 UI 미리보기와 실제 응답에서 같은 역할 순서로 표시할 필요가 있다.

## Goal
체형·포즈·시점·투시·구도 순서, 검색어 복원, 카테고리당 최대 8개 핀을 결정론 함수로 처리한다. 실제 검색과 LLM 호출은 제외한다.

## What
완료된 success/partial_result만 카드로 노출한다. 잘못된 ID/역할·빈 결과·접근 불가 핀을 구분한다. UI 더미는 개발 모드에서 NEXT_PUBLIC_UI_DEMO=1일 때만 활성화된다.

## How
frontend/lib의 term-mind-map, result-view, recommended-query와 demo-job을 사용한다. 기존 검수 카드 JSON은 변경하지 않는다. Next 서버의 AGENT_API_ORIGIN rewrite로 동일 origin API를 연결한다.

## AC
- Given 정상 카드, When 그룹 생성, Then 역할 순서를 유지한다.
- Given 실패 job, When 카드 조회, Then 성공 결과를 표시하지 않는다.
- Given 8개 초과 핀, When 행 생성, Then 상위 8개만 표시한다.
- Given 저장 검색어 또는 search_url, When 검색어 조회, Then 해당 근거에서 복원한다.
- Given 개발 모드 미리보기, When 카드 조회, Then 검수 카드의 용어와 검색어를 사용한다. 더미 Pin은 실제 검색 결과로 주장하지 않는다.
