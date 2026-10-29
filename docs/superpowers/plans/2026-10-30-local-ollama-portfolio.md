# Local Ollama Portfolio Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run the existing Uhkegryo interpretation and personal-term flows on the operator laptop with `qwen3.5:4b-q4_K_M`, without paid or cloud LLM fallback, and measure 30 fixed Korean cases.

**Architecture:** Add an explicit `ollama` provider boundary to the existing OpenAI-compatible adapter. Keep prompt injection, Pydantic contracts, resolver, worker, search, and UI unchanged; only provider construction, portfolio validation, startup preflight selection, and a DB-free evaluation runner change.

**Tech Stack:** Python 3.12, Pydantic Settings, OpenAI Python client pointed at Ollama loopback, Ollama 0.40.13, pytest, existing FastAPI worker contracts.

## Global Constraints

- Model is exactly `qwen3.5:4b-q4_K_M`; no second model or cloud fallback.
- Ollama stays on loopback and uses its default 4096-token context.
- Send `reasoning_effort="none"`; worker concurrency is exactly 1.
- Preserve existing catalog/RAG prompt, Pydantic validation, worker, search, and UI behavior.
- Do not create tunnels, change firewall rules, create credentials, start Langfuse, or read OAuth secrets.
- Live evaluation performs one generation per case and never retries automatically.

---

### Task 1: Fail-closed Ollama settings boundary

**Files:**
- Modify: `backend/shared/config.py:20-162`
- Modify: `backend/tests/test_portfolio_runtime.py:20-74`

**Interfaces:**
- Consumes: environment-backed `Settings` fields.
- Produces: `llm_backend="ollama"`, `ollama_base_url: str`, `ollama_model: str`, and provider-specific portfolio validation.

- [ ] **Step 1: Write failing settings tests**

Add an `OLLAMA_BASE` fixture derived from the existing portfolio base and tests that accept only:

```python
OLLAMA_BASE = BASE | {
    "llm_backend": "ollama",
    "ollama_base_url": "http://127.0.0.1:11434/v1",
    "ollama_model": "qwen3.5:4b-q4_K_M",
    "openrouter_api_key": "",
    "portfolio_free_model_allowlist": "",
    "portfolio_model_catalog_path": "",
}

@pytest.mark.parametrize("change", [
    {"ollama_base_url": "https://ollama.com/v1"},
    {"ollama_base_url": "http://192.168.0.2:11434/v1"},
    {"ollama_base_url": "http://user:pass@127.0.0.1:11434/v1"},
    {"ollama_base_url": "http://127.0.0.1:11434/v1?cloud=1"},
    {"ollama_model": "qwen3.5:4b-cloud"},
    {"ollama_model": "qwen3.5:9b-q4_K_M"},
    {"worker_concurrency": 2},
])
def test_ollama_portfolio_rejects_nonlocal_or_unapproved_runtime(change):
    with pytest.raises((ValidationError, ValueError)):
        Settings(**(OLLAMA_BASE | change))
```

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest backend/tests/test_portfolio_runtime.py -q`

Expected: failures because `ollama` and its settings do not exist.

- [ ] **Step 3: Implement minimal settings validation**

Extend the backend literal and add defaults:

```python
llm_backend: Literal['openrouter', 'codex-cli', 'ollama'] = 'openrouter'
ollama_base_url: str = 'http://127.0.0.1:11434/v1'
ollama_model: str = 'qwen3.5:4b-q4_K_M'
```

Split portfolio provider checks so OpenRouter retains all current API-key/free-price checks, while Ollama requires the exact model, a credential-free HTTP loopback `/v1` URL, no OpenRouter credential, and no external-model catalog fields. Keep common production/CORS/end-time/Langfuse/MCP/concurrency checks shared.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run: `python -m pytest backend/tests/test_portfolio_runtime.py -q`

Expected: all tests pass.

- [ ] **Step 5: Commit**

Run: `git add backend/shared/config.py backend/tests/test_portfolio_runtime.py && git -c commit.gpgsign=false commit -m "feat: add fail-closed Ollama portfolio settings"`

### Task 2: Provider-aware adapter and lifecycle

**Files:**
- Modify: `backend/services/llm.py:258-408`
- Modify: `backend/services/agent_worker.py:713-739`
- Modify: `backend/main.py:33-40`
- Modify: `backend/tests/test_llm_adapter.py:685-719`
- Modify: `backend/tests/test_portfolio_runtime.py:202-249`

**Interfaces:**
- Consumes: `Settings.llm_backend`, `ollama_base_url`, and `ollama_model`.
- Produces: `provider_client_settings(settings) -> tuple[str, str, str]` and provider-specific request fields.

- [ ] **Step 1: Write failing adapter and lifecycle tests**

Use a fake `openai.AsyncOpenAI` constructor to assert the Ollama client receives only
`api_key="ollama"`, `base_url="http://127.0.0.1:11434/v1"`, timeout, and
`max_retries=0`. Use the existing recording completion client to assert an Ollama request contains:

```python
assert request["model"] == "qwen3.5:4b-q4_K_M"
assert request["reasoning_effort"] == "none"
assert "provider" not in request.get("extra_body", {})
```

Add a lifespan test proving `verify_selected_free_model` runs for OpenRouter portfolio mode and is skipped for Ollama portfolio mode. Add a worker-construction test proving Ollama does not instantiate `PortfolioLLMCallBudget`.

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest backend/tests/test_llm_adapter.py backend/tests/test_portfolio_runtime.py backend/tests/test_agent_worker.py -q`

Expected: provider-selection assertions fail.

- [ ] **Step 3: Implement minimal provider selection**

Construct the same adapter with provider-specific values. For Ollama, use its ignored local key and model; add `reasoning_effort="none"` to `_request`. Preserve OpenRouter `extra_body.provider.require_parameters` only for OpenRouter. Gate the free-price preflight and database budget on `llm_backend == "openrouter"`.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run: `python -m pytest backend/tests/test_llm_adapter.py backend/tests/test_portfolio_runtime.py backend/tests/test_agent_worker.py -q`

Expected: all tests pass.

- [ ] **Step 5: Commit**

Run: `git add backend/services/llm.py backend/services/agent_worker.py backend/main.py backend/tests/test_llm_adapter.py backend/tests/test_portfolio_runtime.py && git -c commit.gpgsign=false commit -m "feat: route portfolio inference to local Ollama"`

### Task 3: Fixed 30-case Ollama evaluation

**Files:**
- Create: `evals/ollama-30-v1.json`
- Create: `scripts/run_ollama_eval.py`
- Create: `backend/tests/test_ollama_eval.py`

**Interfaces:**
- Consumes: the v4 prompt, active term-card catalog, `LLMInterpretationAdapter`, `GeneratedPersonalTermDraft`, and a caller-supplied source commit.
- Produces: append-only `metadata.json`, `results.jsonl`, and `review.md` in a new output directory.

- [ ] **Step 1: Write failing runner contract tests**

Test exact fixed IDs `OLLAMA-01` through `OLLAMA-30`, dataset fingerprints, no transport creation during dry-run, no overwrite/resume, one call per model-backed case, sanitized failures, and validation of both interpretation and personal-term JSON. A fake adapter must prove local model identity and `usage="local_gpu"` are recorded without DB access.

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest backend/tests/test_ollama_eval.py -q`

Expected: import failure because the runner does not exist.

- [ ] **Step 3: Add the fixed dataset**

Create 30 synthetic Korean inputs across these exact groups: 10 clear term/combination cases, 8 ambiguity/insufficient-grounding/safety cases, 6 conversation/search-rewrite cases, and 6 personal-term draft cases. Every interpretation expectation names active required/forbidden term IDs; every draft expectation names allowed role/proposal-kind and required JSON fields.

- [ ] **Step 4: Implement the DB-free runner**

Use `SimpleNamespace` settings with the exact local model/base URL and the existing v4 prompt. Interpretation cases call `interpret()` with active cards and then the existing deterministic resolver. Personal-term cases call `_request()` with `SYSTEM_MESSAGE` and the existing strict `GeneratedPersonalTermDraft` schema, then run Pydantic and generated-text validation. Never load `.env`, a DB, user history, or auth files. Stop after configuration errors; record remaining cases as `not_run`.

- [ ] **Step 5: Run runner tests and verify GREEN**

Run: `python -m pytest backend/tests/test_ollama_eval.py -q`

Expected: all tests pass.

- [ ] **Step 6: Commit**

Run: `git add evals/ollama-30-v1.json scripts/run_ollama_eval.py backend/tests/test_ollama_eval.py && git -c commit.gpgsign=false commit -m "test: add bounded Ollama quality evaluation"`

### Task 4: Local operation documentation and configuration examples

**Files:**
- Modify: `.env.example`
- Modify: `docker-compose.yml`
- Create: `docs/local-ollama.md`
- Modify: `README.md`
- Test: `backend/tests/test_compose_distribution.py`

**Interfaces:**
- Consumes: the settings contract from Tasks 1-2.
- Produces: value-safe local configuration examples and startup/verification commands.

- [ ] **Step 1: Write failing distribution assertions**

Assert Compose forwards `LLM_BACKEND`, `OLLAMA_BASE_URL`, and `OLLAMA_MODEL` without embedding credentials; the example uses the exact tag and loopback URL. Document that a container must reach host Ollama through an explicitly configured host alias while Ollama itself remains loopback, so the recommended first evaluation runs the Python backend on the host rather than weakening the bind address.

- [ ] **Step 2: Run the test and verify RED**

Run: `python -m pytest backend/tests/test_compose_distribution.py -q`

Expected: missing Ollama settings assertions fail.

- [ ] **Step 3: Add minimal examples and runbook**

Document installation verification, `ollama pull qwen3.5:4b-q4_K_M`, `ollama ps`, host-backend environment values, evaluation invocation, GPU measurement, stop/restart behavior, and the explicit deferral of public tunneling/firewall changes.

- [ ] **Step 4: Run the test and verify GREEN**

Run: `python -m pytest backend/tests/test_compose_distribution.py -q`

Expected: all tests pass.

- [ ] **Step 5: Commit**

Run: `git add .env.example docker-compose.yml docs/local-ollama.md README.md backend/tests/test_compose_distribution.py && git -c commit.gpgsign=false commit -m "docs: add local Ollama operation guide"`

### Task 5: Live measurement, regression, push, and deployment evidence

**Files:**
- Create locally only: `eval-results/ollama-30-<timestamp>/` (do not commit raw results until reviewed)
- Modify only if evidence requires a fix: files from Tasks 1-4, following a fresh failing regression test.

**Interfaces:**
- Consumes: installed Ollama model and committed runner.
- Produces: measured model identity, quantization, storage size, latency, GPU/CPU split, VRAM, and pass/fail/not-run counts.

- [ ] **Step 1: Verify model identity and warm inference**

Run: `ollama show qwen3.5:4b-q4_K_M`, one schema-bound local request, `ollama ps`, and `nvidia-smi`. Record exact output without secrets.

- [ ] **Step 2: Execute the fixed evaluation once**

Run: `python -m scripts.run_ollama_eval --case-ids <all 30 fixed IDs> --source-commit <full SHA> --output eval-results/ollama-30-<timestamp> --execute`

Expected: 30 terminal rows; no automatic retries. If interrupted, report `not_run` and do not silently resume.

- [ ] **Step 3: Run full verification**

Run backend tests: `python -m pytest backend/tests -q`

Run frontend tests: `npm test --prefix frontend`

Run frontend build: `npm run build --prefix frontend`

Run Compose render only: `docker compose config --quiet`

Run whitespace/secret checks: `git diff --check` and inspect `git status --short`.

- [ ] **Step 4: Commit verified evidence/docs if appropriate and push**

Use command-scoped signature bypass only. Push `main` directly to `https://github.com/sechang405-maker/uhkegryo.git` after confirming remote main still descends from the local base.

- [ ] **Step 5: Verify remote and deployment state**

Confirm the exact remote SHA, GitHub CI status, and Vercel deployment status. Distinguish frontend deployment success from the still-deferred public PC backend connection.

