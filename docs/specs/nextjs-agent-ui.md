# Next.js Agent UI Spec

## Why

- **페르소나**: 캐주얼 캐릭터 일러스트 용어가 익숙하지 않은 초보 사용자
- **상황**: 자연어 설명을 제출하고 Agent의 비동기 해석 결과를 확인한다.
- **문제**: API가 비동기로 동작하므로 입력, polling, 질문, 부분 결과, 실패 상태를 일관되게 안내해야 한다.
- **측정 지표**: 유효 요청 제출 성공률 100%, 종결 Job polling 중단 100%, 실패·질문 상태 메시지 표시 100%

## Goal

- `POST /api/agent`와 `GET /api/jobs/{job_id}`를 동일 origin `/api` 경로로 호출한다.
- queued부터 종결 상태까지 현재 처리 상태를 표시한다.
- `completed`, `needs_clarification`, `partial_result`, `failed`를 API 계약에 맞게 표시한다.
- 데스크톱에서 레퍼런스 보드와 프롬프트 패널을 한 화면에 배치하고, 질문·부분 결과에서 선택 가능한 다음 행동을 제공한다.
- **Out of Scope**: FastAPI 직접 호출, 세션 토큰 저장, 이미지 업로드·생성, 사용자 retry endpoint

## What

**Happy Path**

1. 사용자가 1~500자의 자연어 설명을 입력한다.
2. UI가 UUID `Idempotency-Key`를 생성해 `/api/agent`로 제출한다.
3. `202`와 `job_id`를 받으면 `poll_after_ms` 간격으로 Job을 조회한다.
4. `completed`가 되면 오른쪽에 용어 설명을, 왼쪽에 역할별 원본 Pin 링크와 응답 전용 미리보기를 표시한다.
5. 사용자는 역할 탭을 바꿔 레퍼런스를 비교하고 Pin을 누르면 원본 Pinterest Pin을 새 탭에서 연다.

**Edge Cases**

| 상황 | 처리 |
| --- | --- |
| 빈 입력 또는 500자 초과 | API 호출 없이 입력 오류 표시 |
| `needs_clarification` | 오른쪽에 질문과 직접 입력을 표시한다. 선택형 후속 질문 계약이 활성화된 뒤에는 서버가 승인한 선택지도 표시하고, 선택 시 전체 요청 문장을 입력창에 채워 사용자가 수정·전송한다. 결과 영역은 표시하지 않는다. |
| `partial_result` | 사용 가능한 역할의 결과를 유지한다. 실패 역할에는 안내·검색 링크와 `같은 조건으로 다시 찾기`, `조건 바꿔 입력하기`를 표시한다. |
| `failed` | `user_message`만 표시하고 내부 오류 원문은 표시하지 않음 |
| 세션 쿠키 없음 | `credentials: "include"`로 서버 발급 쿠키 수용 |
| 썸네일이 없거나 Pin이 `deleted` | 이미지 대신 접근 불가 상태를 표시하고 이미지를 다운로드·저장하지 않음 |

### 화면 구성

- 데스크톱: 왼쪽 가변 폭 레퍼런스 보드(약 70~75%), 오른쪽 고정 폭 프롬프트 패널(약 400px). 오른쪽 입력창은 패널 하단에 둔다.
- 왼쪽 상단에는 `reference_plan.terms`에 포함된 역할만 `body → pose → view → perspective → layout` 순서로 탭을 둔다. Pin이 있는 첫 역할을 기본 선택하고, 모든 역할의 Pin이 비었으면 첫 역할을 선택한다. 검색 결과가 비어 있는 역할도 탭을 유지해 사유를 확인할 수 있게 한다.
- 선택한 역할의 `label_ko`, `plain_meaning_ko`, `reference_checkpoints`를 보여 주고, Pin은 원순서의 카드 그리드로 표시한다. 각 카드는 응답 전용 `thumbnail_url`을 쓰고 `pin_url`을 새 탭에서 연다.
- 오른쪽에는 현재 요청, 진행 상태, 선택한 역할의 용어 설명, 질문·안내, 입력창을 순서대로 둔다. 첫 화면에는 입력 예시를 보여 준다.
- 좁은 화면에서는 `레퍼런스`와 `입력·설명` 두 화면을 전환한다. 질문과 선택지는 `입력·설명`에 표시한다.
- 새 요청을 제출하면 이전 레퍼런스 대신 새 Job의 진행 상태를 표시한다. 이 화면은 현재 요청 한 건만 다루며 대화 이력 UI를 제공하지 않는다.

## How

- API base path: `NEXT_PUBLIC_API_BASE_URL=/api`
- 요청: `POST /api/agent`, body는 `request_text`만 포함
- 헤더: UUID 형식 `Idempotency-Key`
- polling: `GET /api/jobs/{job_id}`, `poll_after_ms` 사용
- 진행 상태: `queued | running | validating | searching | rendering`
- 종결 상태: `completed | failed`
- 결과 상태: `success | needs_clarification | partial_result | out_of_scope | unsafe_input`
- 브라우저 저장 금지: session token, anonymous user ID, 원문, Pin thumbnail URL
- Next.js rewrite가 동일 origin `/api/*`를 내부 FastAPI로 전달한다.
- 현재 API에는 `clarification_choices`가 없다. UI는 필드 부재를 빈 배열로 취급하고 `직접 입력`을 항상 제공한다. [선택형 후속 질문 Spec](./clarification-choices.md)의 schema·resolver·assembler·adapter·Prompt·테스트 구현 후 활성화되면 서버의 `{label, request_text}`를 칩으로 표시한다. 누르면 `request_text`를 입력창에 채우되 자동 제출하지 않는다. 새 요청은 새 UUID `Idempotency-Key`로 제출한다.
- 부분 결과의 `같은 조건으로 다시 찾기`는 현재 화면의 메모리에 있는 기존 요청 원문을 새 UUID 키로 다시 제출한다. 원문을 브라우저 영구 저장소에 쓰지 않으며, 새로고침으로 메모리가 사라지면 해당 동작을 표시하지 않는다.
- `검색 링크 열기`는 실패 역할의 서버 제공 `search_url`을 새 탭에서 연다. `조건 바꿔 입력하기`는 기존 요청 원문을 입력창에 채우고 사용자가 수정·전송하게 한다. 두 입력 동작 모두 자동 제출하지 않는다.

## AC

**AC-01 · 입력 검증**

- GIVEN: 사용자가 입력창에 값을 입력한다.
- WHEN: 값이 비어 있거나 1~500자 범위를 벗어난다.
- THEN: API를 호출하지 않고 입력 오류를 표시한다.

**AC-02 · 제출과 세션 쿠키**

- GIVEN: 1~500자의 유효한 입력이 있다.
- WHEN: 사용자가 제출한다.
- THEN: UUID `Idempotency-Key`와 `credentials: "include"`로 `/api/agent`를 호출하고 `202` 응답의 `job_id`를 사용한다.

**AC-03 · polling**

- GIVEN: Job이 진행 상태다.
- WHEN: UI가 Job을 조회한다.
- THEN: `poll_after_ms`를 사용해 polling을 계속하고 진행 상태를 표시한다.

**AC-04 · completed**

- GIVEN: Job 응답이 `completed`다.
- WHEN: UI가 응답을 받는다.
- THEN: 용어 설명과 원본 Pin 링크를 표시하고 polling을 중단한다.

**AC-05 · needs clarification**

- GIVEN: `agent_status=needs_clarification`이고 질문이 있다.
- WHEN: UI가 응답을 받는다.
- THEN: 질문을 표시하고 `reference_plan`은 표시하지 않는다.
- AND THEN: 선택지 필드가 없으면 직접 입력을 제공한다. 후속 계약 활성화 뒤 서버가 선택지를 반환하면 해당 칩을 표시하고, 선택한 항목의 전체 `request_text`를 편집 가능한 입력창에 채우며, 전송 전에는 새 API 요청을 하지 않는다.
- GIVEN: 서버가 `clarification_choices=[]`를 반환한다.
- WHEN: 질문을 표시한다.
- THEN: 선택지 없이 `직접 입력`을 제공한다.

**AC-06 · partial result**

- GIVEN: `agent_status=partial_result`다.
- WHEN: UI가 응답을 받는다.
- THEN: 사용 가능한 결과와 검색 실패 안내를 표시하고 polling을 중단한다.
- AND THEN: 사용 가능한 역할의 Pin을 유지하고, 실패 역할에서 새 Job으로 같은 조건 재검색·서버 검색 링크 열기·조건 수정 중 하나를 선택할 수 있다.
- GIVEN: 사용자가 `같은 조건으로 다시 찾기`를 선택한다.
- WHEN: 현재 화면의 메모리에 원래 요청이 있다.
- THEN: 같은 `request_text`와 새 UUID `Idempotency-Key`로 새 Job을 제출한다.

**AC-07 · failed**

- GIVEN: Job이 `failed`다.
- WHEN: UI가 응답을 받는다.
- THEN: `user_message`만 표시하고 polling을 중단한다.

**AC-08 · 역할별 탐색과 원본 링크**

- GIVEN: 둘 이상의 역할에 Pin이 있는 완료 결과가 있다.
- WHEN: 사용자가 역할 탭과 Pin 카드를 선택한다.
- THEN: 선택한 역할의 용어·확인 포인트·Pin을 원순서로 표시하고, Pin은 원본 `pin_url`을 새 탭에서 연다.

**AC-09 · 화면 전환과 새 요청**

- GIVEN: 데스크톱 또는 좁은 화면에서 결과를 보고 있다.
- WHEN: 화면 폭이 좁아지거나 사용자가 새 요청을 제출한다.
- THEN: 좁은 화면은 `레퍼런스`/`입력·설명`으로 전환 가능하고, 새 요청 제출 후에는 이전 결과 대신 새 Job 진행 상태를 표시한다.
