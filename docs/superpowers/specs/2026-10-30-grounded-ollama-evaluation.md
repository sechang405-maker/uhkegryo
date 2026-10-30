# Grounded Ollama evaluation (2026-10-30)

## Scope

- Source: `7d9f1231f9bfe205ced9c2a97d8040be4e356d50`
- Dataset: unchanged `ollama-30-v1` (20 interpretation, 4 deterministic gates, 6 personal-term drafts)
- Runtime: Ollama loopback, 4096-token context, reasoning disabled, temperature 0, one generation at a time, 800 output tokens
- No database writes, image search, external API, tunnel, firewall, or public default change
- Raw run artifacts:
  - `../eval-results/ollama-grounded-final-4b-20261030`
  - `../eval-results/ollama-grounded-final-9b-20261030`

## Final results

| Model | Package | Loaded processor | Observed total VRAM | Passed | Interpretation | Gates | Personal term | Median / max model latency |
| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `qwen3.5:4b-q4_K_M` | 3.3 GB | 3.1 GB, 100% GPU | 4,125 / 8,151 MiB | 24/30 | 20/20 | 4/4 | 0/6 | 3,071 / 7,129 ms |
| `qwen3.5:9b-q4_K_M` | 6.6 GB | 5.6 GB, 100% GPU | 6,711 / 8,151 MiB | 24/30 | 20/20 | 4/4 | 0/6 | 4,197 / 10,755 ms |

The pre-split full-JSON baselines passed 6/30 for both models. The grounded flow removes model control over state, term IDs, and final JSON, so interpretation semantics now pass through deterministic catalog evidence and resolver checks.

## Model contribution and limitations

- The planner and final JSON work without the model. The model was called for 16 selected interpretations and 6 personal-term cases.
- Only 5/16 4B explanations and 6/16 9B explanations passed strict Korean/catalog grounding. Rejected explanations used the deterministic catalog fallback.
- Neither model changed a search query in any case. Most cards expose one approved query fragment, so search behavior is currently code/catalog driven.
- Both fixed 30-case runs failed all six personal-term generations. A separate one-case reproduction produced valid JSON for both models, so this feature is unstable rather than categorically unsupported; it is not ready as a reliable instructor workflow.
- The planner uses a bounded Korean cue lexicon, not general semantic understanding. It covers literal evidence, negation, conflicts, compound poses, and tested synonyms, but unknown wording deliberately asks for clarification.
- Separate holdouts cover paraphrases for low angle, foreshortening, two-point perspective, wall support, leaping, and A-pose. This reduces exact-sentence fitting but does not establish open-domain Korean robustness.

## Verification

- Grounded planner/enrichment/evaluator/worker: 70 passed.
- Full backend: 1,291 passed, 94 skipped, 1 order-dependent failure. The failing Codex subprocess test passed alone; two unrelated test modules globally select a Windows event loop that cannot spawn subprocesses.
- Frontend: 321 passed.
- Production frontend build: passed on isolated retry. The first parallel build hit a Windows `EPERM` directory race.
- Worker tests cover local search integration, model-failure fallback, clarification without a model call, retry bounds, stale attempts, and cancellation.

## Decision

Use `qwen3.5:4b-q4_K_M` for the next local integration step. It matches 9B interpretation accuracy under this architecture, is faster, and uses about 2.6 GiB less observed VRAM. Do not enable personal-term generation or public remote access yet.
