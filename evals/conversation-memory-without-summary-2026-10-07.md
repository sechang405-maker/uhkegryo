# 자동 요약 없는 대화 기억 검증 (2026-10-07)

## 최종 범위
자동 요약 생성/등록/대기열/소유권/주기 실행과 요약 프롬프트 입력을 제거했다. 현재 조건·확인 질문·최근 6개 원문·필요 시 조회한 원본 출처를 유지한다. prepare는 load만 수행하며 요약 후보를 조회하지 않는다. Memory summarize 출력 스키마와 v4 지침 및 전용 테스트를 제거했다. memory API는 classify/answer만 허용해 summarize를 LLM 전에 거부한다.

load는 constraints/pending_question만 상태로 사용한다. complete는 이 두 필드만 DB JSON에 병합하고 기존 legacy 요약/메타데이터는 일괄 삭제하지 않는다. 과거 검색 원문과 Pin ID·URL·상태도 유지한다. 일반 Job/lease/MCP 캐시 갱신 및 취소 동작을 보존한다.

## 환경
기존 PR #129 head 3ea591b 위에서 작업했다. 운영 이미지 sha256:2b25cf67c7d248db27bc80a0d6a1565397fb963b79516e590d09dbdfe85fb7b4의 Python 3.12.15 / asyncpg 0.31.0, 격리 로컬 PostgreSQL 17 및 LLM 대역으로 검증했다. 코드 mount는 readonly였다. 운영 DB·실제 LLM·배포에는 쓰지 않았다.

## 결과
- 전체 backend: **595 passed, 17 skipped, 1 failed** (15.71s). 실패는 기존 test_eval27_followup_preserves_body_and_pending_question의 pending_question 불일치로 수정 전에도 확인한 동일 assertion이다. 전체 suite 통과로 보고하지 않는다.
- 최종 관련 테스트: **140 passed, 1 deselected** (10.85s). deselected는 위 기존 실패 1개다. 최종 테스트에서는 아래 Pin의 typed history 조회도 추가 검증했다.
- 최근 조건/확인 질문이 포함된 포즈 변경 요청 완료, 기존 체형 보존, 최근 원문 6개 유지, 명시한 포즈 갱신.
- legacy 요약 텍스트/메타데이터는 본문 해석과 회상 분류 입력에서 제외하면서 DB의 기존 데이터는 보존.
- 40개 선행 대화 중 최근 6개에 없는 첫 레퍼런스를 키워드로 조회하고 출처 인용 성공. 다른 session의 같은 문장은 제외됨.
- 오래된 Job 원문/Pin payload 보존 및 history 서비스가 Pin URL을 반환하는 typed 결과 확인.
- summarize 작업 거부 시 LLM transport 호출 0회. v4에 Memory summarize/summary_incomplete 지침 없음.
- prepare의 후보 조회/LLM 호출 없음. worker에서 요약 루프 및 완료 후 등록 없음. 기존 MCP prewarm/갱신/종료, worker/LLM/trace 회귀 통과.
- 위조 출처·다른 대화·stale 저장에 대한 기존 검증을 유지. 제거한 요약 전용 테스트 대신 새 AC 테스트 4개를 추가했으므로 이전 통과 개수와 직접 비교하지 않는다.
- git diff --check 통과.

## 제한
회상 검색의 기존 필터 및 20개 결과 제한은 유지한다. 모호한 오래된 취향/지시와 전체 이력 종합을 자동으로 해결한다고 보장하지 않는다. 실제 사용자 응답 속도의 개선 폭은 배포 후 측정 대상이다. UI/API 계약·모델·검색 엔진·운영 배포는 이번 범위에 포함하지 않는다.

## 최신 main 통합 재검증
main aa9b826의 PR #128 선택적 레퍼런스 갱신과 테스트 계약 수정을 통합했다. conversation_memory.load의 충돌은 previous_result 조회를 유지하면서 요약 전용 oldest_recent를 제거하는 방식으로 해결했다. 원본 보드 유지와 요약 없는 state/프롬프트를 함께 검증한다.

동일 운영 이미지와 격리 로컬 PostgreSQL 17, LLM 대역에서 전체 backend를 다시 실행한 최종 결과는 **623 passed, 17 skipped, 0 failed** (15.99s)다. 기존 질문 보존 테스트도 최신 main의 계약 수정으로 통과했다. 40턴 원본 회상 테스트에 previous_result 보존과 oldest_recent 부재 assertion을 추가했다. 선택적 갱신/전체 및 역할별 재검색, MCP/worker/LLM/trace 테스트도 전체 실행에 포함했다. 운영 DB·실제 LLM·배포는 사용하지 않았다.

## PR
사용자가 기존 #129에서 최종 계획대로 작업하도록 승인했으며 제목/본문은 자동 요약 제거와 원본 기반 기억 유지로 갱신한다. 동일 요약 작업의 400줄 예외는 앞선 사용자 승인을 따른다. 사람의 승인·병합은 수행하지 않는다.
