# MCP 도구 목록과 LLM tool call
## Why

- **페르소나·상황**: 등록 MCP 도구를 사용하는 worker와 이를 선택하는 LLM adapter.
- **문제**: MCP 도구 스키마 조회·호출과 LLM tool-call 응답 처리를 위한 공통 경계가 없다.
- **측정 지표**: 서버가 제공한 스키마에 맞는 등록 도구만 호출하고 결과를 구조화해 반환한다.
## Goal

- MCP `tools/list` 결과를 검증하고 `call_tool` 인자·응답을 공통 gateway에서 처리한다.
- LLM adapter가 전달받은 MCP 스키마로 OpenAI-compatible tool call을 요청하고 결과를 파싱한다.
- **범위 밖**: worker orchestration, Pinterest 결과 변환·재시도, 새 MCP 도구 추가.
## What

1. Gateway가 MCP 도구 이름·설명·입력 스키마를 읽고 LLM tool 정의로 제공한다.
2. LLM adapter가 선택한 도구와 JSON 인자를 반환한다.
3. Gateway가 목록과 스키마를 검증해 도구를 호출하고 구조화된 결과를 반환한다.
## How

- 도구 스키마는 MCP `tools/list`에서 가져오며 worker에 복제하지 않는다.
- 목록에 없는 도구, 스키마에 맞지 않는 인자, 잘못된 MCP 응답은 호출 오류로 처리한다.
- 필수 tool call 누락 또는 잘못된 LLM 응답은 `LLM_INVALID_STRUCTURED_OUTPUT`으로 분류한다.
- 기존 `interpret()` JSON 계약과 MCP 인증·Streamable HTTP 전송을 유지한다.
## AC

- **Given** MCP가 유효한 도구 목록을 반환할 때, **When** gateway가 조회하면, **Then** 이름·설명·입력 스키마를 보존한다.
- **Given** 도구가 목록에 없거나 인자가 스키마와 다를 때, **When** 호출하면, **Then** MCP 실행 전에 거부한다.
- **Given** 유효한 LLM tool-call 응답일 때, **When** 파싱하면, **Then** 도구 이름·호출 ID·객체 인자를 반환한다.
- **Given** 도구 목록이나 필수 LLM 호출이 잘못됐을 때, **When** 처리하면, **Then** 안정된 오류로 실패한다.
