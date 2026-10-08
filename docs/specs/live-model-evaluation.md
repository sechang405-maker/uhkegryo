# Live model evaluation runner

## Why

- Persona: a developer comparing candidate interpretation prompts against the real PostgreSQL worker contract.
- Situation: the runner submits fixed cases and executes them through the worker, but its model adapter can fail before making a request and its results cannot prove out-of-scope behavior.
- Problem: inaccurate runs produce misleading pass rates, while raw validation errors could expose model output or request data in evaluation artifacts.
- Measure: the runner reaches a terminal job state for each selected case, records only bounded safe validation diagnostics, and evaluates server-produced status and search behavior.

## Goal

- Make the measured adapter follow the production adapter request signature.
- Exercise `execute()` through PostgreSQL and `AgentJobWorker` to a terminal job state in an integration test.
- Record safe diagnostics for structured-output validation failures in the runner.
- Make v2-v4 prompts agree with server-owned deterministic unsafe-input and out-of-scope gates.
- Out of scope: changing model/provider settings, running a live 30-case evaluation as part of tests, or storing raw model outputs in diagnostics.

## What

- A request outside the text-based illustration-reference service is classified by a deterministic worker gate after the unsafe-input gate and before conversation memory or LLM work.
- The scope gate detects affirmative unsupported operations only. Explicitly negated or declined operations do not block a separate supported reference search; affirmative unsupported work takes precedence when mixed with reference terms.
- Out-of-scope jobs complete with `agent_status=out_of_scope`, `reason_codes=[OUT_OF_SCOPE_REQUEST]`, no reference plan, and no LLM, resolver, or search calls.
- Candidate prompts describe only the `InterpretationOutput` states accepted by the Pydantic schema and leave final out-of-scope decisions to the worker.
- On `LLMInvalidStructuredOutput`, the worker invokes an optional adapter diagnostic hook with the current attempt. The evaluation adapter records a bounded category and safe schema path/type only; it never records raw exception text, raw model output, or rejected field values.
- The runner integration test uses a dedicated PostgreSQL test URL, a unique temporary schema, repository migrations, EVAL-01 with a stub model response, and asserts a terminal result through the measured request adapter.

## How

- 최신 worker의 검색 주입 경계는 `mcp_gateway`다. 해석 품질 runner는 평가 전용 worker subclass에서 `_search_outcomes`만 fixture로 대체하고, 실제 resolver가 승인한 role/query_fragments로 기존 fixture를 호출한다. 종결·재시도·상태 저장 경로는 실제 worker를 유지한다. MCP tool 선택·네트워크 경로는 이 runner의 검증 범위 밖이며 metadata와 보고서에 명시한다.

- 모호·상충 대조 데이터 추가, 최종 서버 질문의 도메인 단서 검사, 실제 사용자 답변 review.md, 코드 지문 manifest는 [ambiguity-answer-quality.md](ambiguity-answer-quality.md)를 따른다. 정성 점수는 자동 산정하지 않는다.

- Keep `InterpretationState` and resolver states as `select_terms` and `needs_clarification`; use `AgentStatus.OUT_OF_SCOPE` only in the final server result.
- The exact unsupported-operation gate contract and supported categories are documented in `docs/specs/out-of-scope-gate.md`.
- Validation diagnostics use allow-listed output field names, replace unknown path components with `unknown_field`, and cap rendered path/type lengths; raw values and exception messages are never serialized.
- Add `is_out_of_scope_input()` beside input normalization and call it after `is_unsafe_input()` in `AgentJobWorker._process_claimed()`.
- Change `MeasuredAdapter._request(self, messages, *, output_format=None)` and forward `output_format=output_format` to the parent.
- Catch `LLMInvalidStructuredOutput` in the worker's existing failure path and call `record_validation_failure(error, attempt=job["attempt"])` only if the adapter provides that hook.
- Add a PostgreSQL integration test that skips unless `TEST_DATABASE_URL` is configured. Create a random schema, configure every pooled connection's `search_path`, apply all migrations, call `execute()` for EVAL-01 with a stub client, and verify the measured request and terminal result before cleanup.
- Remove `out_of_scope` from v2-v4 candidate output rules and examples; retain final evaluation expectations for EVAL-17 through EVAL-20 because the worker gate owns those results.

## AC

- GIVEN: `interpret()` requests structured output WHEN: `MeasuredAdapter._request()` runs THEN: the parent receives the value as keyword-only `output_format` and no `TypeError` occurs.
- GIVEN: PostgreSQL is available through `TEST_DATABASE_URL` WHEN: the runner integration test calls `execute()` for EVAL-01 THEN: the job reaches its expected terminal result through `MeasuredAdapter._request()`.
- GIVEN: an unsafe input WHEN: the worker claims the job THEN: the unsafe gate runs before scope classification and the terminal result is `unsafe_input`.
- GIVEN: a supported image-reference request WHEN: the worker classifies it THEN: the out-of-scope gate does not intercept it.
- GIVEN: an LLM structured-output validation error WHEN: the worker handles the attempt THEN: only safe bounded diagnostics are recorded and raw error text is absent.
- GIVEN: a Pydantic error location contains an attacker-controlled extra JSON key WHEN: diagnostics are serialized THEN: the path uses `unknown_field`, marker/value/exception text are absent, and the stable `output_schema` category remains.
- GIVEN: a v2-v4 prompt is sent to the model WHEN: its output is validated THEN: it requests only states accepted by `InterpretationOutput` and does not instruct the model to emit `out_of_scope`.
