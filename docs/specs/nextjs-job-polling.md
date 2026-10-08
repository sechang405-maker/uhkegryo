# Next.js Job polling (작업 19)

## Why

- **페르소나**: 자연어 요청을 제출한 초보 사용자
- **상황**: Agent API가 `202 + job_id`를 먼저 반환하고 결과는 나중에 완성한다.
- **문제**: 상태 조회가 없으면 사용자는 요청의 진행·완료·실패를 알 수 없다.
- **측정 지표**: 진행 상태 표시율 100%, 종결 상태 뒤 추가 polling 0회

## Goal

- 접수된 `job_id`로 동일 origin `GET /api/jobs/{job_id}`를 `poll_after_ms`에 맞춰 조회한다.
- 진행 상태를 표시하고 `completed`·`failed`에서 polling을 중단한다.
- **Out of Scope**: 결과 카드·질문·Pin 렌더링(작업 20), 사용자 retry endpoint

## What

1. `POST /api/agent`의 `202`가 준 `poll_after_ms` 뒤 첫 조회를 시작한다.
2. `queued | running | validating | searching | rendering`을 사용자에게 쉬운 상태 문구로 표시한다. 진행 응답의 `poll_after_ms` 뒤에 다시 조회한다.
3. `completed | failed`를 받으면 Job 응답을 메모리에 두고 타이머를 종료한다.
4. 새 Job을 제출하거나 화면을 떠나면 이전 타이머와 진행 중 조회를 취소한다. HTTP·네트워크 오류는 일반 안내를 표시하고 polling을 멈춘다.

## How

- 요청 경로는 `/api/jobs/${encodeURIComponent(job_id)}`이고 `credentials: "include"`를 사용한다. 브라우저 영구 저장소·URL·로그에 Job ID와 원문을 기록하지 않는다.
- 서버가 준 양수 `poll_after_ms`를 사용하며 값이 없거나 유효하지 않으면 1000ms를 사용한다. `setTimeout`으로 다음 요청을 예약해 이전 조회와 겹치지 않게 한다.
- `completed`·`failed`, 오류, cleanup에서는 다음 타이머를 만들지 않는다. 이전 Job의 늦은 응답은 현재 화면 상태를 덮어쓰지 않는다.
- 작업 18의 제출 성공 결과에 `pollAfterMs`를 추가한다. 표시용 상태와 polling은 [UI Spec](./nextjs-agent-ui.md)의 Job 상태 계약을 따른다.

## AC

**AC-01 · 진행 상태**

- GIVEN: `202`의 Job ID와 `poll_after_ms`가 있다.
- WHEN: 첫 조회와 이어지는 진행 응답을 받는다.
- THEN: 지정된 간격으로 조회하고 각 진행 상태를 표시한다.

**AC-02 · 종결과 정리**

- GIVEN: 조회 결과가 `completed` 또는 `failed`다.
- WHEN: UI가 응답을 받는다.
- THEN: 결과를 보관하고 다음 조회를 예약하지 않는다.
- GIVEN: 새 Job이 제출되거나 화면이 사라진다.
- WHEN: 이전 polling을 정리한다.
- THEN: 타이머와 요청을 취소하고 이전 응답이 화면을 바꾸지 못한다.

**AC-03 · 조회 오류**

- GIVEN: API 또는 네트워크 오류가 발생한다.
- WHEN: polling 중 오류를 받는다.
- THEN: 안전한 안내를 표시하고 polling을 중단한다.
