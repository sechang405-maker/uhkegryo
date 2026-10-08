# 후속 요청의 역할별 결과 유지

## Why
초보 일러스트 사용자는 체형과 포즈를 찾은 뒤 포즈만 수정하고 싶다. 불필요한 체형 재검색은 선택한 자료를 잃게 한다. 지표는 변경하지 않은 역할의 검색 호출 0건과 Pin ID 보존이다.

## Goal
명시적으로 변경한 역할만 검색하고 나머지 현재 결과는 유지한다. 다른 대화 참조, 새 UI 버튼, 배포는 제외한다.

## What
- 체형·포즈 결과 뒤 앉은 포즈로 변경하면 포즈만 검색하고 체형과 새 포즈를 함께 표시한다.
- 이전 조건을 출처로 선택한 동일 카드는 재검색하지 않는다. 현재 요청에서 명시적으로 선택·수정한 역할은 검색한다.
- 명시적인 역할 clear는 그 역할을 제거한다. 모호한 변경은 질문하며 이전 결과·기억을 수정하지 않는다.
- 변경 역할의 검색 실패는 해당 역할의 빈 결과·장애 안내로 표시하고 다른 역할은 유지한다.
- 화면은 `reference_update`의 교체 역할만 현재 검색 결과로 갱신하고 유지 역할은 직전 결과의 용어·Pin 데이터를 재사용한다. 삭제 역할은 표시하지 않으며, 확인 질문은 이전 보드를 그대로 보여준다.

## How
- 기존 POST /api/agent와 GET /api/jobs/{id}, 쿠키·session_id 계약을 유지한다.
- 같은 session의 현재 job보다 (created_at, job_id)가 앞선 completed success/partial_result 중 마지막 reference_plan을 읽는다. 회상·거절·질문·실패는 현재 레퍼런스 보드를 대체하지 않는다.
- 서버 전용 이전 결과에는 Pin ID·URL·상태만 있다. LLM에는 기존 정제 기억만 전달하고 Pin·URL을 보내지 않는다.
- 해석과 resolver 검증 후 변경 역할만 MCP에 전달한다. 기존 결과 중 현재 카탈로그에서 활성·역할 일치·직접 검색 가능인 카드만 유지한다.
- 최종 reference_plan은 유지한 역할과 새 역할을 body→pose→view→perspective→layout 순서로 병합한다. 사유 코드와 success/partial_result를 다시 집계한다.
- 유지·교체·삭제 결정은 reference-update-metadata.md의 reference_update에 기록한다. 확인 질문도 기존 보드 유지 역할을 전달한다. 일부 역할의 이미지 교체는 reference-role-refresh.md를 따른다.
- 기존 thumbnail_url 비저장과 완료 응답 widget 재조회, attempt 기반 원자적 저장을 유지한다.
- 이 문서가 conversation-context.md의 '포즈 결과만 반환'을 대체한다: 검색은 포즈만, 전체 보드 응답에는 유지된 체형도 포함한다.

## AC
- Given 체형·포즈 결과, When 포즈만 앉은 자세로 변경, Then MCP pose만 호출하고 체형 Pin ID·URL은 보존한다.
- Given 체형·포즈·시점 결과, When 체형만 근육질로 변경, Then body만 검색하고 포즈·시점 Pin을 보존한다.
- Given 체형·포즈·시점 결과, When 시점만 옆모습으로 변경, Then view만 검색하고 체형·포즈 Pin은 보존한다. 포즈만 변경할 때도 체형·시점 Pin을 보존한다.
- Given 역사 출처의 동일 체형 selection, When 포즈 변경과 함께 해석, Then 체형은 재검색하지 않는다.
- Given 체형·포즈 결과, When pose clear와 새 view 선택, Then 체형은 유지하고 포즈는 제거하며 view만 검색한다.
- Given 모호한 변경, When needs_clarification, Then 검색 없이 질문하고 기존 조건은 보존한다.
- Given pose 검색 장애, When 완료, Then partial_result이며 체형 결과는 유지한다.
- Given 체형·포즈 결과, When 포즈만 다시 검색, Then 체형은 이전 용어·Pin 데이터를 유지하고 포즈만 새 결과로 표시한다.
- Given 역할 부분 갱신 결과, When 역할이 명시적으로 삭제됨, Then 해당 역할을 표시하지 않는다.
- Given 기존 보드와 확인 질문, When clarification 결과를 받음, Then 기존 역할별 용어와 Pin을 그대로 표시한다.
- Given 타 대화 또는 미래 job, When 이전 결과 조회, Then 재사용 대상에 포함하지 않는다.

검증: 2026-10-07 리뷰 대응 후 원래 로컬 수용 기준 27개 및 PR 작업 폴더 전체 backend 647개 통과(임시 PostgreSQL 16), frontend 55개 통과. 기존 로컬 Langfuse 작업은 PR 전체 검증에서 제외했다. 실제 LLM·외부 검색은 fixture로 대체했고 실제 서비스 연동은 미검증이다.
