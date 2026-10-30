"""Bounded, DB-free evaluation of the approved local Ollama model.

The default mode writes fingerprints only. ``--execute`` performs exactly one
generation for each model-backed synthetic case and never resumes or retries.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from pydantic import ValidationError

from backend.schemas.personal_terms import GeneratedPersonalTermDraft
from backend.services.catalog_repository import load_catalog
from backend.services.conversation_context import validate
from backend.services.input_safety import is_out_of_scope_input, is_unsafe_input
from backend.services.llm import (
    LLMConfigurationError,
    LLMError,
    LLMInterpretationAdapter,
    LLMTimeout,
    _extract_content,
    format_active_cards_json,
)
from backend.services.ollama_grounded import OllamaGroundedInterpreter
from backend.services.personal_term_generator import (
    _catalog_grounding,
    _generation_messages,
    _validate_generated_text,
    _validate_semantic_grounding,
)
from backend.services.structured_output import strict_schema


ROOT = Path(__file__).resolve().parents[1]
CASE_IDS = tuple(f"OLLAMA-{index:02}" for index in range(1, 31))
DATASET_VERSION = "ollama-30-v1"
DATASET = ROOT / f"evals/{DATASET_VERSION}.json"
CATALOG = ROOT / "docs/domains/illustration-reference/term-cards"
PROMPT = ROOT / "prompts/uhkegryo-interpreter-v4.md"
DEFAULT_MODEL = "qwen3.5:4b-q4_K_M"
APPROVED_MODELS = frozenset({
    DEFAULT_MODEL,
    "qwen3.5:9b-q4_K_M",
})


class _PersonalTermValidationError(Exception):
    def __init__(self, raw: str, validation_result: str) -> None:
        super().__init__(validation_result)
        self.raw = raw
        self.validation_result = validation_result
BASE_URL = "http://127.0.0.1:11434/v1"
QUANTIZATION = "Q4_K_M"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_cases(ids):
    if tuple(ids) != CASE_IDS:
        raise ValueError("Explicitly select all 30 unique IDs in fixed order")
    dataset = json.loads(DATASET.read_text(encoding="utf-8"))
    if dataset.get("version") != DATASET_VERSION or dataset.get("synthetic_only") is not True:
        raise ValueError("Only the committed synthetic dataset is supported")
    cases = dataset.get("cases")
    if not isinstance(cases, list) or tuple(case.get("id") for case in cases) != CASE_IDS:
        raise ValueError("Dataset IDs differ from the fixed selection")
    snapshot = load_catalog(CATALOG)
    for case in cases:
        if case.get("kind") not in {"interpretation", "gate", "personal_term"}:
            raise ValueError(f"{case['id']}: unsupported case kind")
        for term_id in case.get("expected", {}).get("required_terms", []):
            if snapshot.get_active(term_id) is None:
                raise ValueError(f"{case['id']}: inactive expected term")
    return cases


def make_adapter(model=DEFAULT_MODEL):
    settings = SimpleNamespace(
        llm_backend="ollama",
        ollama_base_url=BASE_URL,
        ollama_model=model,
        llm_model=model,
        openrouter_api_key="",
        openrouter_base_url="https://openrouter.ai/api/v1",
        llm_timeout_seconds=180.0,
        llm_max_tokens=800,
        interpreter_prompt_version="uhkegryo-interpreter-v4",
        interpreter_prompt_path=str(PROMPT),
        structured_output_skill_path=str(ROOT / "skills/structured-output/SKILL.md"),
        langfuse_public_key="",
        langfuse_secret_key="",
    )
    return LLMInterpretationAdapter(settings=settings, prompt_path=PROMPT)


def metadata(commit: str, execute: bool, snapshot, model: str = DEFAULT_MODEL) -> dict:
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("Supply a full reviewed source commit SHA")
    sources = [
        ROOT / "backend/services/llm.py",
        ROOT / "backend/services/ollama_grounded.py",
        ROOT / "backend/services/agent_worker.py",
        ROOT / "backend/shared/config.py",
        Path(__file__),
    ]
    return {
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "mode": "execute" if execute else "dry_run",
        "source_commit": commit,
        "dataset_version": DATASET_VERSION,
        "dataset_sha256": digest(DATASET),
        "selected_case_ids": list(CASE_IDS),
        "requested_model": model,
        "provider": "local_ollama",
        "base_url_scope": "loopback",
        "quantization": QUANTIZATION,
        "context_tokens": 4096,
        "reasoning_effort": "none",
        "prompt_version": "grounded-ollama-v1 (personal terms retain v4 transport)",
        "prompt_sha256": digest(PROMPT),
        "catalog_version": snapshot.dataset_version,
        "catalog_files_sha256": {
            path.name: digest(path) for path in sorted(CATALOG.glob("*.json"))
        },
        "source_files_sha256": {
            path.relative_to(ROOT).as_posix(): digest(path) for path in sources
        },
        "attempts_per_case": 1,
        "maximum_generations": 26,
        "automatic_retry": False,
        "model_judge": False,
        "database": "not used",
        "search_network": "not used",
        "usage": "local_gpu",
        "cost_usd": 0,
        "scope": (
            "deterministic catalog planner plus bounded model explanation/query choice; "
            "personal-term schema remains model-generated; no worker DB or image search"
        ),
    }


class SyntheticMemory:
    async def records(self, _job, _ids):
        return []


def _interpretation_checks(case: dict, interpretation) -> dict[str, bool]:
    expected = case["expected"]
    selected = {item.term_id for item in interpretation.selections}
    return {
        "state": interpretation.interpretation_state.value == expected["state"],
        "required_terms": set(expected.get("required_terms", [])) <= selected,
        "forbidden_terms": not bool(set(expected.get("forbidden_terms", [])) & selected),
    }


def _grounded_checks(case: dict, result, snapshot) -> dict[str, bool]:
    interpretation = result.interpretation
    checks = {"schema": True, **_interpretation_checks(case, interpretation)}
    selected_ids = [item.term_id for item in interpretation.selections]
    expected_clarification = case["expected"]["state"] == "needs_clarification"
    checks["clarification_appropriate"] = (
        bool(interpretation.clarifying_question)
        and not interpretation.selections
        and interpretation.answer_text == ""
        if expected_clarification
        else interpretation.interpretation_state.value == "select_terms"
    )
    if interpretation.interpretation_state.value == "select_terms":
        cards = [snapshot.get_active(term_id) for term_id in selected_ids]
        checks["korean_answer"] = bool(re.search(r"[가-힣]", interpretation.answer_text))
        checks["grounded_answer"] = (
            all(str(card["label_ko"]) in interpretation.answer_text for card in cards)
            and any(
                str(point) in interpretation.answer_text
                for card in cards
                for point in card["look_for"]
            )
        )
    else:
        checks["korean_answer"] = interpretation.answer_text == ""
        checks["grounded_answer"] = interpretation.answer_text == ""
    checks["query_fragments_allowed"] = set(result.query_fragments_by_term) == set(
        selected_ids
    ) and all(
        fragments
        and all(
            fragment in snapshot.get_active(term_id)["query_fragments"]
            for fragment in fragments
        )
        for term_id, fragments in result.query_fragments_by_term.items()
    )
    return checks


def _personal_format() -> dict:
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "personal_term_draft",
            "strict": True,
            "schema": strict_schema(GeneratedPersonalTermDraft.model_json_schema()),
        },
    }


async def _run_interpretation(adapter, case, snapshot):
    result = await OllamaGroundedInterpreter(snapshot, adapter).interpret_grounded(
        case["input"],
        job_id=case["id"],
        session_id="synthetic-ollama-evaluation",
        attempt=1,
        max_attempts=1,
    )
    interpretation = result.interpretation
    resolution = await validate(
        SyntheticMemory(), {"request_text": case["input"]}, interpretation, snapshot
    )
    queries = []
    for term in resolution.terms:
        queries.append({
            "term_id": term.selection.term_id,
            "role": term.selection.role.value,
            "query_fragments": list(result.query_fragments_by_term.get(
                term.selection.term_id, term.card.get("query_fragments", [])
            )),
        })
    return {
        "interpretation": interpretation.model_dump(mode="json"),
        "checks": _grounded_checks(case, result, snapshot),
        "resolution_status": resolution.status,
        "resolved_search_terms": queries,
        "model_called": result.model_called,
        "model_answer_accepted": result.model_answer_accepted,
        "model_output": result.model_raw_output,
        "model_answer": result.model_answer_text,
        "validation_result": (
            "accepted" if result.model_answer_accepted
            else result.model_answer_rejection_reason or "generation_failed"
        ),
        "model_evidence_accepted": result.model_evidence_accepted,
        "model_query_applied": result.model_query_applied,
        "adapter_attempts": int(result.model_called),
    }


async def _run_personal_term(adapter, case, snapshot):
    grounding = _catalog_grounding(case["input"], snapshot)
    messages = _generation_messages(case["input"], grounding)
    response = await adapter._request(messages, output_format=_personal_format())
    raw = _extract_content(response)
    try:
        draft = GeneratedPersonalTermDraft.model_validate_json(raw)
        _validate_generated_text(draft)
        _validate_semantic_grounding(draft, grounding)
    except ValidationError as error:
        raise _PersonalTermValidationError(raw, "invalid_structured_output") from error
    except (ValueError, TypeError, json.JSONDecodeError) as error:
        raise _PersonalTermValidationError(raw, "semantic_or_safety_rejection") from error
    expected = case["expected"]
    return {
        "model_output": raw,
        "validation_result": (
            "accepted_grounded_draft" if grounding else "accepted_ambiguous_draft"
        ),
        "draft": draft.model_dump(mode="json"),
        "checks": {
            "schema": True,
            "role": draft.role.value in expected["allowed_roles"],
            "proposal_kind": (
                draft.proposal_kind in expected["allowed_proposal_kinds"]
                if grounding
                else draft.proposal_kind == "ambiguous"
            ),
        },
    }


def _write_review(path: Path, rows: list[dict], model: str = DEFAULT_MODEL) -> None:
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    lines = [
        "# Ollama 30-case human review",
        "",
        f"- Model: `{model}` (`{QUANTIZATION}`)",
        f"- Status counts: `{json.dumps(counts, ensure_ascii=False, sort_keys=True)}`",
        "- Automated checks cover schemas, gates, catalog IDs, and expected categories only.",
        "- Korean explanation usefulness and drawing accuracy require human review.",
        "",
        "| ID | Category | Status | Checks passed | Latency ms |",
        "| --- | --- | --- | --- | ---: |",
    ]
    for row in rows:
        lines.append(
            f"| {row['id']} | {row['category']} | {row['status']} | "
            f"{row['passed_checks']} | {row['latency_ms']} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


async def run(
    directory,
    ids,
    commit,
    *,
    execute=False,
    adapter_factory=None,
    model=DEFAULT_MODEL,
):
    if model not in APPROVED_MODELS:
        raise ValueError("Use an approved evaluation model")
    cases = load_cases(ids)
    snapshot = load_catalog(CATALOG)
    info = metadata(commit, execute, snapshot, model)
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    (directory / "metadata.json").write_text(
        json.dumps(info, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    if not execute:
        return info

    adapter = adapter_factory() if adapter_factory else make_adapter(model)
    stopped = False
    rows = []
    with (directory / "results.jsonl").open("x", encoding="utf-8") as output:
        for case in cases:
            row = {
                "id": case["id"],
                "category": case["category"],
                "kind": case["kind"],
                "status": "not_run",
                "adapter_attempts": 0,
                "verified_model": None,
                "usage": "local_gpu",
                "cost_usd": 0,
                "checks": {},
                "qualitative_score": None,
            }
            started = time.monotonic()
            try:
                if stopped:
                    pass
                elif case["kind"] == "gate":
                    gate = "unsafe_input" if is_unsafe_input(case["input"]) else (
                        "out_of_scope" if is_out_of_scope_input(case["input"]) else None
                    )
                    row.update(
                        status="deterministic_gate",
                        gate=gate,
                        checks={"gate": gate == case["expected"]["gate"]},
                    )
                elif case["kind"] == "interpretation":
                    row["adapter_attempts"] = 1
                    row.update(await _run_interpretation(adapter, case, snapshot))
                    row.update(status="completed", verified_model=model)
                else:
                    row["adapter_attempts"] = 1
                    row.update(await _run_personal_term(adapter, case, snapshot))
                    row.update(status="completed", verified_model=model)
            except LLMConfigurationError:
                row.update(status="configuration_error", failure_code="CONFIGURATION_ERROR")
                stopped = True
            except LLMTimeout:
                row.update(status="timeout", failure_code="LLM_TIMEOUT")
            except LLMError as error:
                row.update(status="invalid_or_failed", failure_code=error.failure_code.value)
            except _PersonalTermValidationError as error:
                row.update(
                    status="invalid_or_failed",
                    failure_code="INVALID_OR_FAILED",
                    model_output=error.raw,
                    validation_result=error.validation_result,
                )
            except Exception:
                row.update(status="invalid_or_failed", failure_code="INVALID_OR_FAILED")
            row["latency_ms"] = round((time.monotonic() - started) * 1000)
            row["passed_checks"] = bool(row["checks"]) and all(row["checks"].values())
            output.write(json.dumps(row, ensure_ascii=False) + "\n")
            output.flush()
            rows.append(row)
            print(f"{case['id']}: {row['status']}", flush=True)
    _write_review(directory / "review.md", rows, model)
    return info


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case-ids", required=True, help=",".join(CASE_IDS))
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--model", choices=sorted(APPROVED_MODELS), default=DEFAULT_MODEL)
    parser.add_argument("--execute", action="store_true", help="Run the approved local GPU model once per case")
    args = parser.parse_args()
    try:
        asyncio.run(run(
            args.output,
            args.case_ids.split(","),
            args.source_commit,
            execute=args.execute,
            model=args.model,
        ))
    except Exception:
        raise SystemExit(
            "Evaluation setup failed; check arguments and local files. No automatic retry."
        ) from None


if __name__ == "__main__":
    main()
