# 대화별 기억 구현·검증 기록

## 승인 범위
익명 쿠키 소유자 아래 여러 대화를 분리한다. 기존 job 원문과 검증 결과를 재사용하고, 대화별 최근 6개 기록·명시적 조건·미해결 질문·2,000자 요약을 전달한다. 회상은 동일 대화 원본만 조회한다. UI·로그인·외부 RAG는 제외한다.

Spec: [세션](../../specs/conversation-sessions.md), [맥락](../../specs/conversation-context.md), [요약](../../specs/conversation-summary.md), [회상](../../specs/conversation-recall.md).

## 구현 단위
1. API/LLM 데이터 계약과 Spec
2. 익명 소유자 이관·대화 만료·기존 기본 대화 보존
3. 다중 대화 API와 소유권 검증
4. 기존 LLM adapter의 기억 작업과 Prompt
5. 원본 조회·요약·근거 검증·원자적 기억 저장
6. worker 연결·다중 대화 평가·회귀 검증

Git 기준: df92fad04ba0de16eae6e936ffcdb2649976b652. KHS25~KHS30 브랜치에 위 순서대로 분리했으며 각 PR은 직전 브랜치를 기준으로 비교한다. 단계별 코드 변경은 모두 400줄 이하다. 원래 작업 폴더의 미커밋 변경은 수정하지 않았다.

## 검증 기록
- 기준선: 기존 테스트 266 passed, 3 skipped.
- 격리 PostgreSQL에서 기존 cookie/job 보존, 소유권·대화 격리, 만료, 동시 idempotency, stale attempt, 요약 재시도, 회상 원본 검증, EVAL-27 후속 맥락을 실행했다.
- 최종 독립 리뷰: 혼합 요청의 회상 실패 시 새 요청이 생략되는 문제와 카드 라벨·질문의 키워드 검색 누락을 지적했다. 각 재현 테스트의 실패를 확인한 뒤 수정했다. 만료 비교 방향 문서도 바로잡았다.
- 변경으로 SQL이 길어져 기존 잠금 테스트의 pg_stat_activity query 표시가 1KB에서 잘렸다. 실제 advisory 대기를 확인하고 테스트 감지 조건을 쿼리 앞부분으로 변경했다.
- 최신 main 기준으로 단계별 전체 backend 테스트를 다시 실행했고 마지막 단계는 289 passed였다.
- 실제 LLM 평가는 시도했으나 upstream 429로 MEM-01~08 결과를 얻지 못했다. 경과는 evals/memory-live-model-2026-09-30.md에 기록했다. 자동 테스트 결과를 모델 품질 점수로 취급하지 않는다.

## 운영 적용 조건
Neon `dev/conversation-memory-khs25` 브랜치에 003 migration을 적용해 기존 세션 1개와 job 1개 보존을 확인했다. 부모 `production` DB에는 적용하지 않았다. 운영에서는 저장 구조가 바뀌므로 API와 worker를 중지한 뒤 DB 백업, migration, 새 코드/Prompt 배포, 재기동 순서로 적용한다. 이전 코드로 돌아갈 때는 이전 스키마와 함께 복구해야 한다. 앱 startup은 migration을 자동 수행하지 않는다.

## 결정 기록
- 승인된 예외: NOT_BUILD의 외부 지식 금지는 유지하고, 동일 대화의 정제 이력·요약을 허용했다.
- 로그인 users 또는 중복 messages 테이블 대신 anonymous_owners와 기존 sessions/jobs를 사용했다.
- 실제 모델 평가와 UI는 미실행 범위로 구분한다. 기존 FastAPI on_event deprecation 및 SQLite 테스트 설정 경고는 이번 범위에서 수정하지 않았다.
