# 검색 지연 구간 분리

## Why

- 페르소나·상황: 개발자가 느린 검색 요청을 Langfuse에서 분석한다.
- 문제: #116은 엔진별 시도를 기록하지만 LLM 판단, 실행 대기, MCP 왕복, Widget, 결과 API 비용은 구분하지 못한다.
- 지표: 같은 Job의 각 구간 시간과 병렬 역할·재시도 연결을 확인한다.

## Goal

- #116의 engine_attempts와 pinterest-search-{role}을 재사용한다.
- 추가 관측은 검색 결과·동시성·재시도·API 계약을 변경하지 않는다.
- 범위 밖: 검색 정책·timeout 변경, UI·브라우저 표시 시간 측정, 모델 추가, 운영 배포.

## What

1. 검색 상태 DB 갱신, 도구 목록 조회, 검색 도구 선택 LLM, 검색 후 판단 LLM을 구분한다.
2. 역할별 실행 자리 대기, MCP 호출, Widget 조회, 재시도 대기, 결과 조립, 대화 상태 갱신을 기록한다.
3. 반복 Job 조회는 job-result-read 관측을 생성하지 않는다. 완료 조회의 result-widget-refresh 관측만 같은 job_id 기반 trace에 연결한다.
4. 실패·취소도 시간을 기록하되 예외 메시지·인증 정보·이미지 URL·새 사용자 원문은 전송하지 않는다.
5. 관측 초기화·update 실패는 기존 처리에 영향을 주지 않는다.

## How

- 기반: PR #116 / codex/search-engine-tracing. 별도 PR로 추가 변경만 검토한다.
- worker span: search-status-update, mcp-tools-list, mcp-tool-selection, mcp-post-search-decision, search-slot-wait, mcp-search-call, widget-enrichment, search-retry-wait, search-result-assembly, conversation-state-update.
- LLM generation은 기존 부모 span 아래 유지한다. 판단 span metadata에 call_round, purpose, pending_roles, output에 call_count, selected_roles를 기록한다. 검색 외 도구의 인자·본문은 기록하지 않는다.
- 역할별 metadata는 role, search_attempt. Job/attempt 연결은 기존 부모 trace를 따른다. 기존 역할 span에도 search_attempt를 추가한다.
- 공통 output: elapsed_ms(monotonic clock), status(completed/interrupted), 예외 시 error_type(클래스명만).
- Widget output: pin_count, available_count, unavailable_count. Pin status 집계만 기록하며 Pin ID/URL은 추가로 보내지 않는다.
- retry output: planned_ms, reason=pin_search_unavailable 또는 tool_error. 실행 자리 반환 뒤 기존 1초·2초 sleep을 그대로 감싼다.
- search-status-update span은 `searching` 진입 전 상태 DB 갱신만 감싼다. 검색 호출이 생략되는 경로에서는 생성하지 않는다.
- search-result-assembly span은 검색 종료 후 `assemble`과 보존된 검색 결과 병합을 감싼다. 결과에는 집계된 role/pin 수만 기록한다.
- conversation-state-update span은 검색 결과를 반영한 다음 상태 구성 및 저장(`next_state`, `_memory.complete`)을 감싼다. 결과에는 상태 저장 완료 여부만 기록한다.
- MCP latency에는 인증·연결·네트워크·원격 처리가 포함된다. 엔진 latency와의 차이를 순수 네트워크 시간으로 단정하지 않으며 별도 추정 필드를 만들지 않는다.
- 결과 API의 result_read 컨텍스트는 관측을 생성하지 않고 기존 응답 처리용 metrics와 deterministic trace_context만 전달한다. session_id 전파는 유지한다.
- 결과 API의 database_ms와 handler_elapsed_ms는 내부에서만 계산하며 Langfuse로 전송하지 않는다.
- 완료 응답은 result-widget-refresh에 명시적인 trace_context와 Pin 상태 집계를 전달한다. worker 검색·LLM·실패 관측과 기존 결과 조회·인증·쿠키·Widget 동작은 유지한다. 기존 Langfuse 기록 삭제와 운영 배포는 범위 밖이다.
- API tracer는 프로세스에서 재사용하고 종료 시 shutdown한다. 미인증·소유권 실패는 Job trace를 만들지 않는다.
- 검증(2026-10-06): 추가 AC 및 기존 engine/parallel/worker/API/Widget/trace/MCP/LLM/assembler 테스트 104건 통과. 실제 인증 MCP 검색(Pin 8개)과 Widget 조회, 로컬 결과 API(DB 대역)를 공용 Langfuse trace `9902a4c77e7fe9ec27344ea120124039`에서 확인했다. MCP 호출 1.366초, worker Widget 0.913초, 결과 API Widget 0.870초는 단일 검증 기록이며 운영 성능 지표가 아니다. LLM 선택은 대역이며 유료 LLM 호출·운영 배포는 하지 않았다.
- 외부 MCP에는 #116 진단 코드가 미배포되어 위 실측 engine_attempts는 빈 배열이다. 엔진 진단의 보존과 신규 구간 연결은 AC 테스트로 검증했다.

## AC

- AC-01: Given 여러 역할 검색, When searching 단계에 진입해 검색 결과와 대화 상태를 저장, Then 상태 DB 갱신·도구 선택·역할별 wait/MCP/Widget·결과 조립·대화 상태 갱신 시간이 같은 trace에서 구분되며 engine_attempts는 유지된다.
- AC-02: Given unavailable 또는 도구 오류, When 재시도, Then search_attempt와 planned_ms/reason/실제 elapsed_ms가 연결되고 기존 횟수·대기를 유지한다.
- AC-03: Given 동시 Job과 역할, When 한도를 기다리거나 취소, Then 기록이 섞이지 않고 interrupted 시간과 작업 정리가 유지된다.
- AC-04: Given 처리 중·완료 조회, When 소유 사용자가 GET, Then 반복 조회에도 job-result-read 관측은 0개이고 응답은 동일하다. 처리 중에는 관측이 없으며 완료 시 같은 Job trace의 result-widget-refresh와 Widget 집계만 기록한다.
- AC-05: Given 다른 소유자·미인증, When GET, Then 기존 401/404를 유지하고 해당 Job trace를 만들지 않는다.
- AC-06: Given 관측 시작/update 오류, When worker/API 실행, Then 결과·실패 분류를 유지하고 예외 메시지·인증 값·이미지 URL이 신규 관측에 없다.
