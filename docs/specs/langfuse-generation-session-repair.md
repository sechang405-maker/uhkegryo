# 실제 generation 지연과 Sessions 연결

## Why
- 운영자는 generation이 0초로 기록되고 metadata session만 있어 모델 지연·대화 묶음을 볼 수 없다.
- 지표: 실제 호출을 포함한 양수 generation 지연, 같은 session UUID의 표준 sessionId 연결.
## Goal
- interpret·memory·MCP 도구 선택의 실제 호출 시간을 계측하고 worker session을 표준 속성으로 전파한다. generation 이름은 호출 종류로 구분한다.
- 범위 밖: 원격 Prompt 등록, userId/쿠키 기록, 기존 trace 데이터 소급 변경.
## What
- 성공·검증 실패·upstream 실패 generation 모두 호출 시작~응답/예외까지 기록한다.
- SDK 장애는 기존 job 성공/실패 판정을 바꾸지 않는다.
- 재시도와 단계는 기존 job trace에 연결되고 동일 대화는 Sessions에서 묶인다.
## How
- 실제 _request 전 generation 시작; 응답 토큰은 usage_details, 모델과 prompt version을 기록한다. 이름은 `interpreter`, `memory-classify`, `memory-summarize`, `memory-answer`, `mcp-tool-selection` 중 호출에 맞는 값을 사용한다.
- worker observation context에서 propagate_attributes(session_id=UUID)를 사용한다.
- 실패 원문·API key·쿠키·썸네일을 관측에 보내지 않는다. 기존 검증 실패 input=null 규칙 유지.
## AC
- Given 지연된 fake/실제 LLM, When 호출 종료, Then generation 시작이 호출보다 앞서고 양수 지연이 기록된다.
- Given 같은 session의 job/재시도, When 관측, Then 표준 sessionId가 같고 trace는 job별로 유지된다.
- Given SDK 실패, When job 처리, Then 동일 결과와 오류 계약을 유지한다.
- Given 각 LLM 호출 종류, When generation을 기록, Then 이름은 종류별로 구분되고 모델·prompt version은 기존 필드에 유지된다.
- Given 실제 Cloud Run 요청, When Langfuse API/UI 조회, Then generation 지연·토큰·모델·Sessions 연결을 확인한다.
