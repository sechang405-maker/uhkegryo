# 요약 연결 복구 검증 (2026-10-07)

## 변경
PR #124의 ec8391e 위에서 수정·검증한 변경을 사용자 요청에 따라 기존 branch `codex/memory-latency`에 추가한다. 이번 PR의 400줄 제한 예외는 사용자가 명시적으로 승인했다. 요약 연결이 닫힌 경우 원래 pool release 전에 공개 API `terminate()`로 정리한다. 정상 연결은 기존 release/reset으로 반환한다. 이미 해제된 proxy의 InterfaceError는 무시하되 작업의 원래 예외는 유지한다. 풀 수·최대 연결 수·LLM·배포는 변경하지 않았다.

## 환경과 재현
- 운영 이미지: `asia-northeast3-docker.pkg.dev/proj2-509406/docker-repo/api@sha256:2b25cf67c7d248db27bc80a0d6a1565397fb963b79516e590d09dbdfe85fb7b4`
- 이미지의 Python 3.12.15 / asyncpg 0.31.0, 격리된 로컬 PostgreSQL 17.11.
- LLM은 event 기반 대기로 대체했다. 운영 DB 및 실제 LLM을 호출하지 않았다.
- 수정 전: LLM 대기 중 pg_terminate_backend 후 즉시 재개하는 타이밍에서 닫힌 연결의 슬롯 반환이 누락됐다. max_size=1에서 후속 작업이 timeout했고, max_size=10 반복 재현에서는 가용 queue가 10→0으로 감소했다. 잠금은 다른 연결에서 획득 가능했으므로 잠금 누적과 구별된다.

## 수정 후 결과
- 신규 회귀 테스트: 4 passed. max_size=1 및 10에서 각각 20회 강제 단절 후 매번 모든 슬롯을 동시에 acquire했고, 같은 풀의 SELECT 및 최종 요약 저장이 성공했다. 이미 해제된 proxy의 원래 예외 보존과 정상 연결 PID 재사용도 통과했다.
- 원래 외부 fault probe 7개 시나리오: 대상 없는 반복 실행, unlock SQL 실패, LLM 대기 중 단절, unlock 시 단절, unlock/reset 실패, unlock 중 취소, 정리 중 재취소. 모두 정리 후 다른 연결의 잠금 획득 및 같은 풀의 후속 요약 성공을 확인했다.
- 기존 max_size=10 단절 probe 30회: 매번 queue_size=10 유지, 후속 DB 작업 timeout 없음. 연결 재생성 전 idle 연결 수와 빌릴 수 있는 슬롯 수는 구분한다.
- 전체 backend tests: **584 passed, 17 skipped, 1 failed** (16.07s). 실패는 `test_eval27_followup_preserves_body_and_pending_question`의 pending_question 불일치다. 앞선 수정 전 baseline에서도 같은 assertion 실패를 확인했으며 이번 변경 범위에서 수정하지 않았다. 전체 suite 통과로 보고하지 않는다.

## 근거와 한계
격리 실험 원본 JSON은 `D:\ai human\archives\proj2-4\pr124-recovery-2026-10-07`의 `fault-results.json`, `pool10-fixed-results.json`에 보관했다. 신규 테스트는 `backend/tests/test_summary_connection_recovery.py`다.

이번 수정은 연결 단절 후 풀 용량 손실을 방지한다. 요약 LLM 대기 중 정상 연결 점유 시간은 줄이지 않으며 실제 사용자 응답 지연의 개선 폭은 운영 트레이싱으로 별도 측정해야 한다. 검증 시점에는 커밋·푸시·배포를 수행하지 않았다. 이후 사용자 요청에 따라 기존 PR #124에 변경을 올리며 배포는 이번 작업 범위에 포함하지 않는다.
