# LLM Markdown 답변 지침

## Why
초보자가 통합 설명의 용어·관찰점·주의 사항을 구분해 읽을 수 있어야 한다.

## Goal
answer_text 문자열 안에 한국어 Markdown 답변을 작성하도록 지시한다.

## What
- 짧은 문단을 기본으로 필요할 때만 ### 소제목, 굵게, 목록, 주의 인용을 사용한다.
- 핵심 한국어 용어는 처음 등장할 때만 굵게 표시한다.
- 짧은 답변에 불필요한 섹션을 강제하지 않는다.
- 전체 답변을 코드 펜스로 감싸지 않고 HTML·이미지·링크·표·코드 블록을 만들지 않는다.
- 정보 부족 시 빈 answer_text, 내부 ID 비노출, 근거 제한과 4000자 상한은 유지한다.

## How
LLM adapter의 시스템 작성 지침을 추가한다. JSON 스키마·DB·모델·재시도·추가 호출은 바꾸지 않는다.

## AC
- 모델에 전달하는 메시지에 Markdown 작성 및 금지 요소 지침이 포함된다.
- 기존 adapter와 MCP tool call 테스트가 통과한다.
- 실제 모델의 작성 준수는 별도 라이브 호출 전까지 미검증으로 표시한다.

## 검증 결과
- OSC21 adapter·MCP tool call 테스트 70개 통과.
- 3002 연결 API를 재빌드했고 MARKDOWN_GUIDANCE_ACTIVE=True와 health 200을 확인했다.
- 초기 적용 확인 시 유료 요청은 보내지 않았다. 이후 승인된 화면 요청은 LLM_INVALID_STRUCTURED_OUTPUT로 실패했으므로 실제 모델의 Markdown 작성 품질은 미검증이다.

## 통합 PR 검증 (2026-10-02)
- origin/main a0c49f7 기준으로 통합했다. PR107의 v4 작성·복구 지침, 기억 분류 정규화, 모호한 요청의 조건 갱신 방지를 보존했다.
- 백엔드 전체 테스트: 492 passed, 28 skipped, 5 warnings. 실제 PostgreSQL 등 환경 의존 테스트의 미실행을 통과로 계산하지 않는다.
- 프런트 테스트: 51 passed. Production build 통과. npm ci --ignore-scripts 성공, npm audit 보고 0 vulnerabilities.
- 원문·모델 출력 없이 내부 검증 진단만 보존한다. 신규 실패 원인이나 라이브 답변 품질은 이번 PR 생성 과정에서 유료 호출로 재검증하지 않았다.
- 이번 통합 PR에 한해 사용자에게 400줄 제한 예외 승인을 받았다. 자동 생성 lockfile을 포함한다.
