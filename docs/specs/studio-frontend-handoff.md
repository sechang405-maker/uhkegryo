# Studio 프론트 백엔드 연결 인수인계

## Why
프론트 PR 병합을 서버 연결·실제 지속 대화 완성으로 오해하지 않도록 한다.

## Goal
현재 프론트가 사용하는 API와 남은 팀 작업을 명확히 한다. 백엔드 구현·운영 DB 변경은 제외한다.

## What
- POST /api/agent: request_text, Idempotency-Key, 쿠키. 202 응답의 job_id와 poll_after_ms 사용.
- GET /api/jobs/{job_id}: job_status, poll_after_ms, result 또는 failure.user_message 사용.
- 완료 결과의 result.answer_text: 한국어 통합 설명. 없는 경우 user_message 또는 연결 예정 안내.
- result.reference_plan.terms: term_id, role, label_ko, plain_meaning_ko, 검색어/URL, 핀 목록.
- POST /api/term-search: term_id, suffix(drawing/sketch/mannequinization). 같은 카드의 TermResult 반환.

## How
NEXT_PUBLIC_UI_DEMO=0, NEXT_PUBLIC_API_BASE_URL=/api, AGENT_API_ORIGIN=<팀 백엔드 origin>을 설정하고 Next 서버를 재시작한다. .env는 커밋하지 않는다. UI는 같은 origin /api를 요청하고 Next rewrite가 백엔드로 전달한다. 배포 환경에서 익명 쿠키의 Path/Domain/Secure/SameSite를 점검한다.

## AC
- Given 실제 연결, When 사용자 입력, Then job 접수→폴링→통합 답변과 핀 목록을 확인한다.
- Given 재검색, When 성공/실패, Then 해당 행만 변경하거나 기존 결과를 유지한다.
- Given 이전 요청의 후속 질문, When 처리, Then 백엔드가 이전 조건을 전달하는지 별도 검증한다.
- Given 새로고침, When 실제 이력 복원, Then 서버 이력 API를 추가 연결한 뒤 검증한다.

## 현재 미완료 경계
실제 대화의 answer_text 전달·서버 이력 복원·명시적 session_id 제출은 `studio-conversation-connection.md`로 연결한다. 개발 더미만 localStorage에 텍스트를 저장한다. 실제 모델의 답변 의미 품질과 운영 환경의 쿠키·DB 연결은 별도 QA로 확인한다. 검색 공급자와 term-search 엔드포인트는 이 연결 변경에 포함하지 않는다.
