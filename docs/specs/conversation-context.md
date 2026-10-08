# 후속 요청의 대화 맥락
## Why
EVAL-27과 확인 질문에 대한 후속 메시지는 현재 요청만으로 해석할 수 없다.
## Goal
동일 대화의 최근 6개 종결 job과 현재 조건, 미해결 질문을 해석에 연결한다. 다른 대화·외부 문서 사용은 제외한다.
## What
사용자의 명시적 조건과 수정은 역할별로 기억한다. 추천은 사용자 확정 사실로 바꾸지 않는다. 회상만으로 현재 조건을 수정하지 않는다. 안전 거절/실패 job은 조건을 갱신하지 않는다.
## How
sessions.memory_json의 constraints(role→term_id/evidence/source_job_id)와 pending_question을 사용한다. 최근 6개 및 회상 원본은 jobs다. 기존 요약 메타데이터는 호환을 위해 보존하되 입력·판단에는 사용하지 않는다.
LLM 입력 session_context는 서버 전용이다. 정제된 job에는 job_id/요청/선택카드의 ID·역할·라벨/질문·안내만 포함한다. URL·Pin·썸네일은 포함하지 않는다.
InterpretationSelection.source_job_id는 nullable UUID다. null이면 현재 요청 evidence를 확인하고, 값이 있으면 같은 대화의 선행 원본 요청 또는 검증된 카드 라벨의 실제 인용인지 확인한다. source_job_id만으로 조건을 변경하지 않는다.
원본 검증을 통과한 selection의 출처별 요청·카드 라벨만 resolver의 `verified_source_texts`에 전달한다. resolver는 해당 source_job_id의 텍스트로 근거를 확인하며 현재 요청에 같은 인용이 존재할 것을 요구하지 않는다. source_job_id만 전달하고 검증된 출처 텍스트가 없으면 거부한다. 활성 카드·역할·검색 가능성 검사와 시작 시 의존 참조 검증은 유지한다.
구조화 context_updates는 현재 요청의 명시적 근거를 가진 역할별 set/clear만 허용한다. set 카드에 resolver와 같은 활성/역할/의존 검증을 적용한다. 모호하면 기존 조건을 유지하고 질문한다.
needs_clarification 완료에서는 context_updates를 적용하지 않고 pending_question만 갱신한다. 알려진 기존 조건을 그대로 보존하며, mode=none의 사용하지 않는 회상 필터는 adapter에서 빈 값으로 정규화한다. 상세 계약은 ambiguity-answer-quality.md를 따른다.
worker는 선행 종결 job만 사용한다. job 완료와 memory_json 갱신은 attempt/상태/만료를 확인한 한 transaction이다. failed·stale attempt는 기억을 쓰지 않는다.
자동 요약을 생성하지 않으며 본문 해석에는 현재 조건·확인 질문·최근 6개 원문·검증된 출처만 전달한다. 상세 제거 및 호환 계약은 conversation-summary-background.md를 따른다.
## AC
- Given A의 체형, When B 요청, Then A 기록은 prompt에 없다.
- Given 앞선 체형과 포즈, When 포즈만 변경 요청, Then 체형 검색·Pin은 유지하고 포즈만 검색해 전체 보드를 반환한다. 상세 계약은 selective-reference-update.md를 따른다.
- Given 확인 질문, When 짧은 답, Then 이전 질문이 prompt에 포함된다.
- Given 확정된 체형과 모호한 후속 요청, When 모델이 질문과 체형 clear 후보를 반환, Then 서버가 조립한 최종 질문만 pending_question에 저장해 다음 prompt에 전달하고 체형 조건은 보존한다. 마지막 포즈 변경 응답은 체형과 새 포즈를 함께 반환한다.
- Given 타 대화 출처/없는 인용/비활성 카드, When 출력 검증, Then 결과와 기억 저장을 거부한다.
- Given 현재 요청에는 없고 동일 대화의 선행 요청 또는 카드 라벨에만 있는 인용과 유효한 source_job_id, When 원본 검증과 resolver를 실행, Then selection을 허용한다.
- Given 선행 출처 인용이 있지만 검증된 출처 텍스트가 없거나 카드가 비활성·역할 불일치, When resolver를 실행, Then selection을 거부한다.
- Given stale attempt, When 완료, Then job과 memory 모두 변경되지 않는다.

검증(2026-10-07): 현재 계약에 맞춘 두 PostgreSQL 통합 테스트와 진단 보존 관련 테스트 15개 통과. 기존 로컬 Langfuse 변경을 제외한 PR 작업 폴더에 동일 테스트 수정을 적용해 전체 backend 636개 통과(실제 임시 PostgreSQL 16, LLM·검색 fixture).
