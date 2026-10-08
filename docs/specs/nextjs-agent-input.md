# Next.js 입력과 요청 제출 (작업 18)

## Why

- **페르소나**: 드로잉 용어가 익숙하지 않은 초보 사용자
- **상황**: 캐릭터 설명을 입력해 비동기 Agent 작업을 시작한다.
- **문제**: 빈 입력·길이 초과를 서버에 보내거나 중복 제출하면 불필요한 Job이 생긴다.
- **측정 지표**: 잘못된 입력의 API 호출 0건, 유효 제출의 UUID 키·쿠키 포함률 100%

## Goal

- 1~500자의 자연어 설명을 검증하고 동일 origin `POST /api/agent`로 제출한다.
- 성공한 `202`의 `job_id`를 현재 화면 메모리에 보관하고 접수 상태를 표시한다.
- **Out of Scope**: Job polling(작업 19), 결과·질문·Pin 렌더링(작업 20), 대화 이력, 브라우저 영구 저장소

## What

1. 첫 화면은 왼쪽 레퍼런스 영역과 오른쪽 프롬프트 패널을 보여 준다. 왼쪽은 후속 작업 전까지 결과 대기 안내만 표시한다.
2. 사용자는 오른쪽의 설명 입력창에 1~500자를 입력하고 전송한다. 빈 문자열·공백만 있는 문자열·500자 초과 입력은 입력창 아래 오류로 알리고 API를 호출하지 않는다.
3. 유효한 제출은 진행 중 중복 클릭을 막고, `202`가 오면 `job_id`를 메모리에 유지하며 접수 안내를 표시한다. 새 요청을 제출하면 이전 접수 안내를 지운다.
4. HTTP 오류는 서버의 `user_message`가 있으면 표시하고, 응답 형식 오류·네트워크 오류는 일반 안내를 표시한다. 내부 오류 원문은 화면에 표시하지 않는다.

## How

- Next.js App Router의 클라이언트 입력 컴포넌트를 사용한다. 프론트는 `frontend/`에 두고 `next.config.mjs`에서 `/api/:path*`를 서버 전용 `AGENT_API_ORIGIN`(기본값 `http://127.0.0.1:8000`)의 `/api/:path*`로 rewrite한다. 브라우저 호출 경로는 항상 `/api/agent`다.
- JavaScript 문자열의 Unicode code point 수(`Array.from(request_text).length`)를 1~500자로 검사한다. 공백만 있는지 `trim()`으로 확인하되 유효한 원문은 수정하지 않고 전송한다.
- 전송마다 `crypto.randomUUID()`로 새 UUID `Idempotency-Key`를 만든다. 요청 헤더는 `Content-Type: application/json`과 `Idempotency-Key`; 본문은 `{request_text}` 하나만 포함하고 `credentials: "include"`를 사용한다.
- `202` 응답에서 문자열 `job_id`를 읽는다. 입력 원문과 Job ID는 React 메모리에만 두며 localStorage·sessionStorage·URL·로그에 기록하지 않는다. 다른 상태 코드 또는 `job_id` 누락은 성공으로 표시하지 않는다.
- 작업 18의 접수 화면은 polling을 시작하지 않는다. `job_id`는 작업 19에서 polling에 연결한다. `clarification_choices`는 [선택형 후속 질문 Spec](./clarification-choices.md)의 후속 구현 범위다.

## AC

**AC-01 · 입력 검증**

- GIVEN: 빈 문자열, 공백만 있는 문자열 또는 500자를 넘는 입력이 있다.
- WHEN: 사용자가 전송한다.
- THEN: 입력 오류를 표시하고 `fetch`를 호출하지 않는다.

**AC-02 · 정상 제출**

- GIVEN: 1~500자의 유효한 입력이 있다.
- WHEN: 사용자가 전송한다.
- THEN: UUID `Idempotency-Key`, `credentials: "include"`, `{request_text}`만 담은 본문으로 동일 origin `/api/agent`를 한 번 호출한다.
- AND THEN: `202`의 `job_id`를 현재 화면 메모리에 보관하고 접수 안내를 표시한다.

**AC-03 · 오류와 중복 전송**

- GIVEN: 요청이 진행 중이거나 서버가 오류를 반환한다.
- WHEN: 사용자가 다시 전송하거나 오류 응답을 받는다.
- THEN: 진행 중 추가 요청을 막고, 실패 시 서버의 안전한 `user_message` 또는 일반 안내를 표시한다.
