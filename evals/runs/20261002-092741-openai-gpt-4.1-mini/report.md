# 실제 모델 30건 평가

- 실행: 2026-10-02T09:27:41.910975+09:00
- 모델: `openai/gpt-4.1-mini` / 카탈로그: `0.8-json-runtime-catalog-reviewed`
- 검사한 기대값 일치: **30/30**
- 실제 모델 응답: 57회 / 총 토큰: 368510
- 문항 지연 p50/p95: 12.66s / 15.58s
- 정성 점수: 지정 도메인 평가자와 독립 검토자 검토 전, 미산정.
- 실제 PostgreSQL·worker·adapter·resolver·assembler 실행. 검색은 fixture.
- 미검사: HTTP 202·cookie 인증·MCP 네트워크/provenance·실제 Pinterest·Langfuse 전송·질문 must_address·정성 품질. 전체 계약 준수율이 아님.

| 문항 | 판정 | 실제 상태 | 불일치 검사 |
|---|---|---|---|
| EVAL-01 | PASS | success | - |
| EVAL-02 | PASS | success | - |
| EVAL-03 | PASS | success | - |
| EVAL-04 | PASS | success | - |
| EVAL-05 | PASS | success | - |
| EVAL-06 | PASS | success | - |
| EVAL-07 | PASS | success | - |
| EVAL-08 | PASS | success | - |
| EVAL-09 | PASS | success | - |
| EVAL-10 | PASS | success | - |
| EVAL-11 | PASS | success | - |
| EVAL-12 | PASS | needs_clarification | - |
| EVAL-13 | PASS | needs_clarification | - |
| EVAL-14 | PASS | success | - |
| EVAL-15 | PASS | needs_clarification | - |
| EVAL-16 | PASS | needs_clarification | - |
| EVAL-17 | PASS | out_of_scope | - |
| EVAL-18 | PASS | out_of_scope | - |
| EVAL-19 | PASS | out_of_scope | - |
| EVAL-20 | PASS | out_of_scope | - |
| EVAL-21 | PASS | unsafe_input | - |
| EVAL-22 | PASS | unsafe_input | - |
| EVAL-23 | PASS | success | - |
| EVAL-24 | PASS | partial_result | - |
| EVAL-25 | PASS | success | - |
| EVAL-26 | PASS | partial_result | - |
| EVAL-27 | PASS | success | - |
| EVAL-28 | PASS | success | - |
| EVAL-29 | PASS | success | - |
| EVAL-30 | PASS | JOB_INSTANCE_INTERRUPTED | - |

제공자가 응답에 기록한 총 비용(USD): 0.1226924
