# Grounded Local Ollama Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move Ollama state, catalog selection, search authorization and final JSON assembly into deterministic code while limiting the model to grounded Korean explanation and approved search-fragment choice.

**Architecture:** A new Ollama-only grounded interpreter scores active TERM_CARD evidence and returns a server-built `InterpretationOutput`. A bounded enrichment call can only choose existing query fragments and write a grounded Korean explanation; the worker passes validated fragments into the existing local search and response assembly path.

**Tech Stack:** Python 3.13, Pydantic, OpenAI-compatible Ollama API, pytest, existing async worker and TERM_CARD catalog.

## Global Constraints

- Preserve OpenRouter, Codex, API and UI contracts.
- Do not install another model or make a paid/cloud inference call.
- Keep Ollama loopback-only and do not change public defaults, networking, secrets or authentication.
- Use the unchanged 30-case dataset for both installed models.

---

### Task 1: Deterministic catalog planning

**Files:**
- Create: `backend/services/ollama_grounded.py`
- Test: `backend/tests/test_ollama_grounded.py`

**Interfaces:**
- Produces: `plan_grounded_request(request_text: str, snapshot: CatalogSnapshot) -> InterpretationOutput`
- Consumes: immutable active cards and existing input normalization.

- [ ] Write failing tests proving explicit slim body, contrapposto, combined sitting/low-angle and exact front/full-body inputs select literal expected IDs without an LLM.
- [ ] Write failing tests proving vague, conflicting and close-score unsupported inputs return the correct clarification and no search selection.
- [ ] Run the focused tests and confirm failures are caused by the missing planner.
- [ ] Implement normalized catalog scoring, exact-label weighting, ambiguity margin and server-side `InterpretationOutput` assembly.
- [ ] Run focused resolver and planner tests until green.
- [ ] Commit the verified planner.

### Task 2: Bounded explanation and query enrichment

**Files:**
- Modify: `backend/services/ollama_grounded.py`
- Test: `backend/tests/test_ollama_grounded.py`

**Interfaces:**
- Produces: `GroundedInterpretationResult` containing `interpretation` and validated `query_fragments_by_term`.
- Consumes: `LLMInterpretationAdapter._request` with a small Pydantic response schema.

- [ ] Write failing tests proving a model cannot change state or term IDs, cannot introduce a query fragment, and cannot return non-Korean or ungrounded explanation text.
- [ ] Run tests and observe the intended failures.
- [ ] Implement the one-call bounded enrichment and deterministic explanation/query fallback.
- [ ] Run focused tests and mutation-check wrong-ID, wrong-fragment and empty-response branches.
- [ ] Commit the verified enrichment.

### Task 3: Ollama-only worker integration

**Files:**
- Modify: `backend/services/agent_worker.py`
- Test: `backend/tests/test_agent_worker.py`

**Interfaces:**
- Consumes: `GroundedInterpretationResult` from the Ollama adapter.
- Produces: existing `AgentResult` and existing search provider calls with validated fragments.

- [ ] Write failing tests proving Ollama constructs the grounded adapter, passes only validated query fragments to local search, and uses default fragments when enrichment fails.
- [ ] Add regression tests proving OpenRouter/Codex construction and result-card contracts are unchanged.
- [ ] Implement optional grounded-result handling without changing other adapter paths.
- [ ] Run worker cancellation, retry, search failure and personal-term regression tests.
- [ ] Commit the verified worker integration.

### Task 4: Evaluation and integration evidence

**Files:**
- Modify: `scripts/run_ollama_eval.py`
- Modify: `backend/tests/test_ollama_eval.py`
- Modify: `docs/local-ollama.md`

**Interfaces:**
- Produces: separate immutable result directories for 4B and 9B grounded runs.
- Consumes: the original `ollama-30-v1` cases and expected meaning.

- [ ] Write failing evaluation tests for separate JSON validity, semantic term checks, clarification, Korean grounding and search-fragment checks.
- [ ] Update the runner to use the grounded adapter and record model-call versus deterministic-only latency.
- [ ] Run both installed models once per eligible case with 4K context, concurrency 1 and non-thinking mode.
- [ ] Manually inspect representative raw explanations and classify parser, truncation and semantic failures separately.
- [ ] Run isolated worker integration tests without the user database, then the full backend/frontend suites and build.
- [ ] Document before/after metrics, GPU/CPU split, remaining failures and the still-unconnected public path.
- [ ] Commit and push to `main`, then verify the exact remote SHA, GitHub CI and Vercel deployment status.
