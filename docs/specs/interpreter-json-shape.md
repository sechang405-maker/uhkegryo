# Interpreter v1 출력 구조 전달

## Why

- 페르소나: 레퍼런스 UI에서 자연어 요청을 제출하는 사용자
- 상황: OpenRouter 호출은 성공하지만 `selections`가 배열이 아닌 출력이 생성된다.
- 문제: v0 파일의 JSON 계약과 예제는 adapter가 읽는 System message 밖에 있어 실제 모델 입력에는 포함되지 않는다.
- 지표: 실제 System message의 필수 출력 필드 누락 0건.

## Goal

- v1의 단일 System message에 selection 항목의 구조와 두 해석 상태의 JSON 형태를 전달한다.
- 실제 OpenRouter 호출을 Pydantic과 resolver로 검증한다.
- Out of Scope: 로컬 LLM 설치, provider rate limit 해제, 출력 자동 보정, API schema 변경, 무제한 재시도.

## What

- v0를 보존하고 `uhkegryo-interpreter-v1`을 새 버전으로 제공한다.
- `selections`와 `evidence`는 배열이고 selection은 `{role, term_id, evidence, confidence, source_job_id}`임을 명시한다. `context_updates`도 최상위 배열로 포함한다.
- `selections[].evidence`는 현재 요청 또는 유효한 `source_job_id`가 지정한 동일 대화의 선행 원본 요청·카드 라벨에서 원문 철자·영문 대소문자를 그대로 인용한다.
- `context_updates[].evidence`는 현재 요청에서만 원문 철자·영문 대소문자를 그대로 인용한다. 조건 변경에는 `source_job_id`가 없으며 선행 원본·카드 라벨만으로 변경을 정당화할 수 없다. 한국어 출력 제한은 `unresolved_constraints`와 `clarifying_question`에만 적용한다.
- 선택 상태와 질문 상태를 각각 하나의 JSON 예제로 설명한다. 예제 ID는 실제 후보가 아니며 활성 카드의 ID로 대체해야 한다.
- 잘못된 출력은 기존 검증에서 거부한다. HTTP 429 및 timeout 정책은 기존 계약을 따른다.

## How

- `prompts/uhkegryo-interpreter-v1.md`는 의미 해석과 근거 출처 규칙만 담당한다. 출력 구조와 예제는 [출력 Skill](./structured-output-skill.md)의 Runtime instructions에 한 번만 두며, adapter가 v1에서 이를 결합한다. loader는 기존 두 메시지 추출 방식을 유지한다.
- Docker image에 v0와 v1을 모두 포함한다.
- 최신 main의 `session_context`, `source_job_id`, `context_updates` 계약과 Memory classify·summarize·answer 지시문을 유지한다. v1의 출력 예제에도 nullable 출처와 조건 변경 배열을 포함한다.
- 서버의 조건 변경 카드 검증은 resolver에 현재 `request_text`를 전달한다. 선택 항목의 선행 출처를 조건 변경 근거로 사용하지 않는다.
- 선행 출처 검증을 통과한 selection은 [대화 맥락 계약](./conversation-context.md)에 따라 출처별 원본 텍스트를 resolver에 전달해 검사한다. 현재 요청에 해당 인용이 없어도 활성·역할 검증을 통과하면 허용한다.
- v1은 비활성 준비용 프롬프트다. 이 PR은 `.env.example`과 배포 설정을 v0에서 변경하지 않는다. 평가와 팀 검토 뒤 별도 활성화 변경에서 Prompt 경로와 버전을 함께 v1로 지정한다.
- v1 활성화 시 `INTERPRETER_PROMPT_PATH=./prompts/uhkegryo-interpreter-v1.md`, `INTERPRETER_PROMPT_VERSION=uhkegryo-interpreter-v1`을 함께 지정한다.
- v1은 [구조화 출력 Skill Spec](./structured-output-skill.md)의 코드 유래 strict schema를 사용한다. v0의 `response_format=json_object`는 유지하며 두 버전 모두 SDK 내부 재시도 0회, `InterpretationOutput` 및 resolver 검증을 유지한다.
- 원본 모델 출력은 영구 저장하지 않는다. 로컬 검증에서는 오류 위치와 타입만 출력한다.

## AC

- GIVEN v1 파일과 출력 Skill, WHEN adapter가 System message를 결합하면, THEN 현재 `InterpretationOutput`의 출력 구조와 두 상태 예제가 Skill에서 한 번만 포함된다.
- GIVEN System message 안의 선택·질문 예제, WHEN 예제 JSON을 검증하면, THEN 모두 `InterpretationOutput`을 통과한다.
- GIVEN 현재 요청 또는 유효한 `source_job_id`의 선행 원본·카드 라벨에 영어 단서가 있다, WHEN v1의 `selections[].evidence`로 인용하면, THEN 대소문자를 포함한 원문 철자를 유지한 채 구조 검증을 통과한다.
- GIVEN 현재 요청에 영어 조건 변경이 명시돼 있다, WHEN 해당 원문을 `context_updates[].evidence`로 반환하면, THEN `conversation_context.validate()`를 통과한다.
- GIVEN 조건 변경 근거가 선행 원본 요청·카드 라벨에만 존재하고 현재 요청에는 없다, WHEN `context_updates[].evidence`로 반환하면, THEN 서버 검증은 `LLM_INVALID_STRUCTURED_OUTPUT`으로 거부한다.
- GIVEN 현재 요청에는 없고 유효한 선행 요청·카드 라벨에만 있는 selection 근거, WHEN `conversation_context.validate()`를 실행하면, THEN 출처 검증과 resolver를 통과한다. 없는 출처·인용·비활성 카드·역할 불일치는 계속 거부한다.
- GIVEN 출력 Skill의 예제와 코드 유래 Schema, WHEN 현재 Pydantic 모델 필드와 비교하면, THEN `source_job_id`와 `context_updates`를 포함해 필드가 일치한다.
- GIVEN `selections=null` 또는 객체, WHEN 기존 출력 검증을 수행하면, THEN `LLM_INVALID_STRUCTURED_OUTPUT`으로 거부한다.
- GIVEN Docker image, WHEN v1 경로를 설정하면, THEN 해당 파일을 읽고 v1을 trace 버전으로 사용한다.
