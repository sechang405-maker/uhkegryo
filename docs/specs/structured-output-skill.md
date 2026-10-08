# Structured output Skill

## Why

- 페르소나: 자연어 설명으로 역할별 레퍼런스를 찾는 사용자.
- 문제: 출력 예제가 해석 프롬프트와 섞여 관리되고, JSON mode만으로는 필드 타입을 보장하기 어렵다.
- 지표: 호출에 Skill·코드 유래 schema 누락 0건.

## Goal

- 기존 v1 해석 프롬프트에 출력 Skill을 결합해 같은 호출에 함께 전달한다.
- `InterpretationOutput`을 schema의 단일 원천으로 유지한다.
- Out of Scope: 새 의미 해석 프롬프트 버전 추가, v1 해석 규칙 변경, API 필드 변경, 모델 출력 자동 보정, 별도 JSON 생성 LLM, 원격 production Prompt 변경.

## What

- 의미 해석·카드 선택·근거 출처·조건 변경은 `prompts/uhkegryo-interpreter-v1.md`의 규칙을 사용한다. 대화 기억 지시문은 유지하되 출력 필드·타입·상태별 구조·예제는 출력 Skill로 모은다.
- `skills/structured-output/SKILL.md`는 출력 형태·상태별 규칙·검증 오류의 수정 방식을 설명한다.
- v1에서 Skill이 없거나 읽기 불가면 설정 오류로 호출 전에 실패한다. v0는 Skill을 읽거나 결합하지 않는다.
- provider가 schema를 지원하지 않으면 기존 upstream 오류 정책을 적용하며 JSON mode로 자동 폴백하지 않는다.

## How

- `STRUCTURED_OUTPUT_SKILL_PATH` 기본값은 `skills/structured-output/SKILL.md`이다. Docker image에 파일을 포함한다.
- `INTERPRETER_PROMPT_VERSION=uhkegryo-interpreter-v1`일 때만 adapter가 해석 System message와 Skill의 `Runtime instructions`를 합친다. v0는 기존 System message, `response_format=json_object`, provider 옵션 부재를 유지하며 검증 피드백도 모델 메시지에 추가하지 않는다.
- v1 해석 프롬프트에는 JSON 객체·필수 필드·배열/nullable 타입·상태별 구조·출력 예제를 두지 않는다. 이 지시와 예제는 결합된 system message의 출력 Skill에 한 번만 존재하며 필드·enum·범위의 기계 검증은 코드 유래 Schema가 담당한다.
- `InterpretationOutput.model_json_schema()`로 `response_format={type:json_schema,json_schema:{name:interpretation_output,strict:true,schema:...}}`를 만든다.
- strict object의 `required`에는 모든 properties를 넣고 `default`는 제거한다. nullable 필드는 null을 유지하며 Pydantic 필드나 모델을 바꾸지 않는다.
- OpenRouter 요청은 `provider.require_parameters=true`로 schema 지원 endpoint에 한정한다. 호출은 attempt당 1회, SDK 재시도는 0회다.
- 위 schema는 해석 호출에 적용한다. main의 대화 기억 classify·summarize·answer 호출은 각 기존 출력 계약을 유지하며 해석 schema를 적용하지 않는다. 서버가 제공하는 `session_context`와 `InterpretationOutput`의 대화 맥락 필드는 유지한다.
- v1을 사용하는 환경은 `INTERPRETER_PROMPT_PATH=./prompts/uhkegryo-interpreter-v1.md`와 `INTERPRETER_PROMPT_VERSION=uhkegryo-interpreter-v1`을 함께 지정한다. 기존 v0 배포 기본값은 이 변경에서 전환하지 않는다. 서버의 Pydantic·resolver 검증은 유지한다.
- 검증 범위는 v1과 Skill의 결합, 코드 유래 schema, 검증 오류 처리다. 의미 해석 품질은 별도 실제 평가가 필요하며 단위 테스트를 실제 모델 평가 점수로 표시하지 않는다.

## AC

- GIVEN v1 경로·버전과 Skill, WHEN adapter가 호출하면, THEN 하나의 system message에 v1의 지시문과 출력 Skill이 포함되고 JSON Schema는 코드의 필드·enum·범위를 반영하며 trace 버전은 v1이다.
- GIVEN Skill 파일 부재, WHEN 초기화하면, THEN `CONFIGURATION_ERROR`로 실패하며 LLM을 호출하지 않는다.
- GIVEN provider schema 응답, WHEN 검증하면, THEN 역할 중복·순서·상태 불변 조건을 계속 검증한다.
- GIVEN v0 기본 설정과 존재하지 않는 Skill 경로, WHEN 해석하면, THEN 기존 프롬프트와 JSON mode로 한 번 호출하고 Skill·strict schema·provider 옵션·검증 피드백을 추가하지 않는다.
- GIVEN v1 결합 메시지, WHEN 출력 형식 지시와 두 상태 예제를 검사하면, THEN 출력 Skill에만 각각 한 번 존재하고 예제는 `InterpretationOutput`을 통과한다.
