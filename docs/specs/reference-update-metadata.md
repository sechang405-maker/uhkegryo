# 역할별 보드 갱신 메타데이터
## Why
역할별 화면을 만드는 클라이언트는 응답만으로 서버가 유지·교체·삭제한 역할을 알아야 한다. 이전 이미지 비교 추론 없이 갱신 결정을 전달하는 것이 지표다.
## Goal
정상·부분 결과와 확인 질문 응답에 서버가 확정한 갱신 정보를 제공한다. 프런트 UI 변경·배포는 제외한다.
## What
포즈 변경은 pose 교체와 body/view 유지, clear는 삭제, 전체 교체는 모든 현재 역할 교체다. 확인 질문은 기존 보드 역할 전부 유지하며 검색·삭제하지 않는다. 최초 보드의 새 역할은 교체 목록에 포함한다.
## How
- AgentResult.reference_update는 nullable 객체이며 replaced_roles/preserved_roles/removed_roles 배열을 가진다. 기존 저장 응답·다른 결과 생산자는 null 기본값으로 호환한다.
- 각 배열은 Role enum, 최대 5개, 중복과 배열 간 겹침을 거부한다. 서버는 body/pose/view/perspective/layout 순서로 조립한다.
- 정상·부분 결과의 교체+유지 목록은 최종 보드의 모든 역할과 정확히 일치해야 한다. 확인 질문의 교체·삭제 목록은 빈 배열만 허용한다. 다른 agent_status에는 null만 허용한다.
- worker의 success/partial_result/needs_clarification에 반드시 제공한다. 질문은 reference_plan=null 계약을 유지한다. 기존 보드가 없으면 유지 목록도 비어 있다.
- 정상 결과에서 교체는 검증된 검색 대상 중 최종 결과에 포함된 역할, 유지는 나머지 최종 역할, 삭제는 이전 보드 역할 중 최종 보드에 없는 역할이다. 빈 Pin·검색 실패도 해당 역할의 새 빈 결과로 교체한다.
- 확인 질문에서는 직전 보드의 모든 역할을 유지한다. 메타데이터는 LLM 출력으로 받지 않으며 원본 Pin/URL을 모델에 전달하지 않는다.
- API 조회/DB JSON 직렬화에 포함하고 thumbnail 비저장·소유권·선행 job·attempt 계약은 유지한다.
## AC
- Given 세 역할 보드, When 포즈 변경, Then replaced=[pose], preserved=[body,view], removed=[]이며 최종 보드는 세 역할이다.
- Given 역할 clear, When 완료, Then 삭제 역할은 removed에만 포함된다.
- Given 모호한 변경 또는 잘못된 이미지 교체 범위, When 확인 질문, Then reference_plan=null이고 replaced/removed는 비며 기존 보드 역할은 모두 preserved다.
- Given 최초 요청, When 완료, Then 새 역할만 replaced에 있고 preserved/removed는 비다.
- Given 검색 실패, When 부분 결과, Then 해당 역할은 replaced에 있고 다른 역할은 preserved다.
- Given 저장 후 조회, When AgentResult 재검증, Then 메타데이터가 동일하며 이전 응답에 필드가 없으면 null이다.

검증(2026-10-07): 원래 로컬 수용 기준 27개, PR 작업 폴더 전체 backend 647개, frontend 55개 통과. 실제 PostgreSQL 16에서 부분 교체·확인 질문 메타데이터의 저장·재조회를 확인했다. LLM·검색은 fixture로 대체했다.
