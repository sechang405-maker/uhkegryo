# 배포 장애 보완 및 재검증 — 2026-10-04

LLM 출력 오류, Pin 검색 장애, generation 시간 계측 및 Sessions 연결을 보완하고 Preview에 반영했다. 이전 실패 기록은 그대로 남기며, 아래 결과는 수정 후 새 Job으로 검증했다.

## 변경

- [출력 계약](specs/interpreter-catalog-output-repair.md): v4에 카탈로그 role/term enum과 역할별 nullable 슬롯을 적용한다. 외부 API에는 기존 순서의 배열을 반환하며 Pydantic/resolver/evidence 검증을 유지한다. 확인 질문·범위 밖 응답은 모든 슬롯이 null이다. Preview `LLM_MAX_TOKENS=2048`.
- [메모리 의도](specs/memory-intent-routing-repair.md): 과거 요청과 문장이 같아도 새 검색이면 none, 과거 추천을 묻는 질문이면 recall이다. 실제 모델에서 두 경우를 확인했다.
- [Pin 검색](specs/pin-search-engine-recovery.md): Google Images → DuckDuckGo Images → 공식 SearXNG Pinterest 엔진 순서로 검색한다. 최초 정상 Pin 응답에서 종료하며 엔진별 15초, 최대 3회다. 기존 HTTPS/숫자 Pin ID/중복 제거/8개 상한과 실패 코드를 유지한다.
- [관측](specs/langfuse-generation-session-repair.md): 해석·메모리·MCP 도구 선택의 실제 호출 구간을 generation으로 기록하고 표준 session_id를 전파한다. SDK 장애가 job 결과를 바꾸지 않는 계약을 유지한다.

파일 Prompt/모델은 v4와 `openai/gpt-4.1-mini`이며, adapter의 전송 계약과 실행 지침이 보완됐다. 기존 v4 평가 결과를 이번 구현의 품질 통과 근거로 사용하지 않는다. 원격 Prompt 등록·production label 승격은 이번 변경에 포함하지 않았다.

## 최종 배포

| 서비스 | revision | 이미지 SHA256 |
|---|---|---|
| API/worker | `api-preview-00005-9dz` | `16772daf3dd63bb8799282da6e58784831f4a4d29deded1f965021bcdb86221b` |
| MCP 검색 | `mcp-preview-00004-fcs` | `7c9d31862c3ee6ba767c1b19d63299ea2e4ed4e51f811d5fe74ed82bd927f431` |
| 두 서비스의 SearXNG | 각 sidecar | `fa86944792d82eb8bd616ade391b779ba7c4585b442277853a9ffc3690dc8e65` |

두 서비스는 최신 revision에 100% 트래픽을 전환했다. API health=200, MCP 인증 없는 접근=403을 확인했다. Vercel UI 검증은 로그인된 Chrome에서 수행했다.

## 실제 통합 검증

| 입력 | 결과 | attempt | Pin 및 썸네일 | 전체 시간 | Job |
|---|---|---|---|---|---|
| front_full | success | 1 | view 8개 | 26.69초 | `4c98bd4e-f68f-4d79-91b6-7be80dbcb176` |
| slim_pose | success | 1 | body 8개, pose 8개 | 25.28초 | `2f8340c7-ba0d-436f-be3d-3bbc3cee7755` |
| followup | success | 1 | pose 8개 | 25.27초 | `44dc99d6-fa28-4767-b554-ed2d3da94b40` |
| clarify | needs_clarification | 1 | 해당 없음 | 16.99초 | `2ce23b58-3f9e-484c-a32e-6349bfca8152` |
| fresh_three_roles | success | 1 | body 8개, pose 8개, view 8개 | 45.53초 | `dc7e74e8-7dba-47aa-94f8-24ef997de6ec` |

정면·전신, 체형·포즈, 포즈만 변경은 같은 세션의 연속 Job이었다. 확인 질문 및 새 3역할 요청은 마지막 API revision에서 검증했다. Pin 숫자는 썸네일 반환 숫자와 같았다. 지원 범위 밖 입력은 첫 시도에 out_of_scope로 완료했다.

이전 Vercel 대화에서 동일 요청을 반복했을 때 정상 답변과 체형/포즈 Pin 16개가 복구됐고, 새로고침 후 답변이 유지됐다. 제출 idempotency와 API 대화 복원(200)도 확인했다.

![Vercel 통합 답변과 Pin 복구](C:/Users/PC/.codex/visualizations/2026/10/04/01a104ec-148d-7551-9375-06878d4f9b38/repair-app-success.png)

## Langfuse

- 마지막 revision의 확인 질문: generation 2개, 2.130/2.134초, 같은 표준 sessionId.
- 마지막 revision의 새 3역할 요청: generation 5개, 1.922~7.928초, 토큰/모델 기록과 표준 sessionId 확인. 전체 요청 시간은 외부 검색·썸네일 조회를 포함해 45.53초였다.
- 연속 대화 3개 Job은 [Sessions 상세](https://35.253.105.218.sslip.io/project/portfolio-traces/sessions/6a599f56-cdd7-47fb-847c-4f15d82cca6d)에서 Total traces=3, Total cost=$0.036756으로 묶였다. MCP 도구 선택 호출도 비용 집계에 포함된다.

![Sessions 3개 trace 연결](C:/Users/PC/.codex/visualizations/2026/10/04/01a104ec-148d-7551-9375-06878d4f9b38/repair-langfuse-session.png)

## 회귀 검증과 운영 한계

- 최종 adapter/schema/worker/trace/provider 테스트: 116 passed.
- 추가 memory/MCP/resolver 회귀: 29 passed, 15 skipped. 생략된 테스트는 별도 테스트 DB 등 실행 조건이 필요한 항목이다.
- git diff --check 통과.
- Google/DuckDuckGo 403은 외부 엔진의 응답으로 남아 있다. 마지막 Pinterest 경로가 실제 연속 요청을 복구했다. 모든 외부 엔진이 장애이면 기존 partial_result/PIN_SEARCH_UNAVAILABLE 계약을 따른다.
- 토큰 상한만 올렸을 때도 확인 질문이 잘려 실패했다. nullable 슬롯과 기존 빈 배열 예시의 충돌을 명시적으로 보완한 후 로컬 실제 모델 3회 연속 및 마지막 Cloud Run 요청이 첫 시도에 통과했다.
- 이 검증은 위 고정 입력과 실제 운영 연결에 대한 확인이며, 전체 평가셋의 새 품질 점수를 주장하지 않는다.

CI 보완(2026-10-04): term-search의 전체 엔진 장애 fixture를 Google/DuckDuckGo/Pinterest 모두 unresponsive로 수정했다. 단일 Google 장애 뒤 정상 빈 fallback은 PIN_RESULTS_EMPTY 계약이다. Windows 로컬 backend 전체 497 passed / 28 skipped. 같은 head a0596d7의 GitHub Actions run 37193819018 (Linux/Python 3.12)은 496 passed / 29 skipped이며 두 결과의 출처를 구분한다. 실행 코드 변경 없이 테스트만 보완했다.

## 2026-10-05 재리뷰 보완
최신 #111 설정을 통합했다. API 토큰 상한의 단일 기준은 cloudbuild.yaml deploy-api의 LLM_MAX_TOKENS=2048이며 새 환경에서도 같은 값을 적용한다. 배포 후 서비스 JSON에서 API 컨테이너의 해당 env 값 2048을 확인하는 절차는 vercel-deployment Spec에 명시한다. 비용 운영 승인이 없으면 신규 배포를 차단한다. 이번 재리뷰에서 실제 서비스를 재배포하지 않았으며, 위 10/4 revision/실모델 검증은 당시 고정 기록이다.
최신 통합 후 Windows 로컬 전체 backend: 509 passed / 28 skipped (외부 LLM/trace 비활성화). Actions 결과는 별도 기록한다.
