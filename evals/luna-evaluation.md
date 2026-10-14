# Local Luna interpretation evaluation

The separate `scripts.run_luna_eval` path leaves the OpenRouter/DB worker runner unchanged. It uses only the committed `luna-16-v1.json`, v4 prompt and local catalog. It never retrieves existing conversations or initializes a DB, search client, worker or model judge.

From repository root, with backend dependencies installed:

```powershell
$cases = (1..16 | ForEach-Object { 'LUNA-{0:D2}' -f $_ }) -join ','
python -m scripts.run_luna_eval --case-ids $cases --source-commit <reviewed-full-commit-sha> --output <new-output-directory>
```

This default only writes a fingerprint manifest. After human authorization, add `--execute` to consume the existing ChatGPT-authenticated Codex subscription allowance. No API key, paid fallback, automatic retry, run resumption or external search is used. Do not rerun a failed/partial run without accounting for already consumed calls and obtaining authorization for additional calls. Each fixed case is considered once, with at most one generation. Four safety/scope cases normally stop at deterministic production input gates, yielding twelve model calls, not sixteen model-quality successes. Authentication/configuration failures stop subsequent generations.

Metadata records the caller-supplied source commit (not falsely described as Git-verified), actual backend/runner file hashes, prompt and catalog JSON hashes, dataset version/hash, requested model, low reasoning effort and timeout. On a successful real adapter return, the existing runtime has verified the exact `gpt-5.6-luna`/`openai` header; failed calls have unknown verified model. Tokens, subscription usage and monetary cost remain `unknown`. OpenRouter temperature/max_tokens are not claimed as CLI controls.

Each result is flushed separately. Exception messages, command lines, environment, auth files and raw malformed outputs are not persisted. Only schema-valid output derived from synthetic input is retained for review, including when deterministic grounding later rejects it. The two context cases use fixed in-memory synthetic sources; they do not assess DB retrieval, recall classification or conversation persistence.

`passed_checks` covers expected state, required/forbidden terms and deterministic grounding. It is not a semantic-quality score: `qualitative_score` stays null until documented review. Review term/evidence consistency, explanation correctness, novice observation guidance and clarification sufficiency with the existing rubric. Keep original results and distinguish model output error, expectation error, catalog limit, resolver defect and evaluator defect. Never change expectations just to raise the score.

Tests patch the actual adapter's transport and DB entrypoints; no real model calls belong in CI.
