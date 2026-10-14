"""Explicit, bounded synthetic interpretation evaluation. Default: no model calls.

Run from repository root with python -m scripts.run_luna_eval. Never imports a
worker, DB pool, application settings, .env, or user conversation storage.
"""
import argparse
import asyncio
import hashlib
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from backend.services.catalog_repository import load_catalog
from backend.services.codex_llm import CodexInterpretationAdapter
from backend.services.codex_runtime import MODEL
from backend.services.conversation_context import validate
from backend.services.input_safety import is_unsafe_input, is_out_of_scope_input
from backend.services.llm import format_active_cards_json, LLMConfigurationError, LLMError, LLMTimeout

ROOT = Path(__file__).resolve().parents[1]
CASE_IDS = tuple(f'LUNA-{i:02}' for i in range(1, 17))
DATASET_VERSION = 'luna-16-v2'
DATASET = ROOT / f'evals/{DATASET_VERSION}.json'
CATALOG = ROOT / 'docs/domains/illustration-reference/term-cards'
PROMPT = ROOT / 'prompts/uhkegryo-interpreter-v4.md'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_cases(ids):
    if tuple(ids) != CASE_IDS:
        raise ValueError('Explicitly select all 16 unique IDs in fixed order')
    dataset = json.loads(DATASET.read_text(encoding='utf-8'))
    if dataset['version'] != DATASET_VERSION or dataset.get('synthetic_only') is not True:
        raise ValueError('Only the committed synthetic dataset is supported')
    cases = dataset['cases']
    if tuple(case['id'] for case in cases) != CASE_IDS:
        raise ValueError('Dataset IDs differ from the fixed selection')
    snapshot = load_catalog(CATALOG)
    for case in cases:
        expected = case['expected']
        for term in expected.get('required_terms', []):
            if snapshot.get_active(term) is None:
                raise ValueError(f"{case['id']}: inactive expected term")
        for role, term in expected.get('final_constraints', {}).items():
            card = snapshot.get_active(term)
            if card is None or card['role'] != role:
                raise ValueError(f"{case['id']}: invalid expected context constraint")
    return cases


def make_adapter():
    # Deliberately avoid Settings()/environment/.env and any database URL.
    settings = SimpleNamespace(interpreter_prompt_version='uhkegryo-interpreter-v4',
        interpreter_prompt_path=str(PROMPT), llm_model=MODEL, codex_timeout_seconds=180,
        codex_executable='', codex_bin_dir='', langfuse_public_key='', langfuse_secret_key='')
    return CodexInterpretationAdapter(settings=settings, prompt_path=PROMPT)


def check_output(case, output):
    expected = case['expected']
    selected = {item.term_id for item in output.selections}
    checks = {'state': output.interpretation_state.value == expected.get('state'),
            'required_terms': set(expected.get('required_terms', [])) <= selected,
            'forbidden_terms': not bool(set(expected.get('forbidden_terms', [])) & selected)}
    if 'final_constraints' in expected:
        state = {role: value['term_id'] for role, value in case['context']['constraints'].items()}
        for update in output.context_updates:
            state[update.role.value] = update.term_id
        checks['context_updates'] = all(state.get(role) == term for role, term in expected['final_constraints'].items())
        checks['context_selections'] = all(item.term_id == expected['final_constraints'][item.role.value]
            for item in output.selections if item.role.value in expected['final_constraints'])
    return checks


class SyntheticMemory:
    def __init__(self, case):
        self.records_by_id = {r['job_id']: r for key in ('recent', 'sources')
                              for r in (case.get('context') or {}).get(key, [])}

    async def records(self, job, ids):
        return [self.records_by_id[str(i)] for i in ids if str(i) in self.records_by_id]


def metadata(commit, execute, snapshot):
    if not re.fullmatch('[0-9a-f]{40}', commit):
        raise ValueError('Supply a full reviewed source commit SHA')
    sources = sorted((ROOT/'backend').rglob('*.py')) + [Path(__file__)]
    return {'started_utc': datetime.now(timezone.utc).isoformat(),
        'mode': 'execute' if execute else 'dry_run', 'source_commit': commit,
        'commit_provenance': 'caller supplied; source hashes identify actual files',
        'dataset_version': DATASET_VERSION, 'dataset_sha256': digest(DATASET),
        'selected_case_ids': list(CASE_IDS), 'requested_model': MODEL,
        'provider': 'openai', 'prompt_sha256': digest(PROMPT),
        'prompt_version': 'uhkegryo-interpreter-v4', 'catalog_version': snapshot.dataset_version,
        'catalog_files_sha256': {p.name: digest(p) for p in sorted(CATALOG.glob('*.json'))},
        'source_files_sha256': {p.relative_to(ROOT).as_posix(): digest(p) for p in sources},
        'reasoning_effort': 'low', 'timeout_seconds': 180, 'attempts_per_case': 1,
        'maximum_generations': 16, 'automatic_retry': False, 'model_judge': False,
        'database': 'not used', 'search': 'not used', 'usage': 'unknown', 'cost_usd': 'unknown',
        'scope': 'interpretation and deterministic validation; no DB recall, worker, HTTP or images'}


async def run(directory, ids, commit, *, execute=False, adapter_factory=None):
    cases = load_cases(ids)
    snapshot = load_catalog(CATALOG)
    info = metadata(commit, execute, snapshot)
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)  # Never resume/retry a prior run.
    (directory/'metadata.json').write_text(json.dumps(info, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    if not execute:
        return info
    adapter = (adapter_factory or make_adapter)()
    stopped = False
    with (directory/'results.jsonl').open('x', encoding='utf-8') as output_file:
        for case in cases:
            row = {'id': case['id'], 'category': case['category'], 'status': 'not_run',
                   'adapter_attempts': 0, 'verified_model': None, 'usage': 'unknown',
                   'cost_usd': 'unknown', 'checks': {}, 'qualitative_score': None}
            started = time.monotonic()
            try:
                gate = 'unsafe_input' if is_unsafe_input(case['input']) else (
                    'out_of_scope' if is_out_of_scope_input(case['input']) else None)
                if gate:
                    row.update(status='deterministic_gate', gate=gate,
                               checks={'gate': gate == case['expected'].get('gate')})
                elif not stopped:
                    row['adapter_attempts'] = 1
                    interpretation = await adapter.interpret(case['input'],
                        job_id=case['id'], session_id='synthetic-evaluation', attempt=1, max_attempts=1,
                        active_cards_json=format_active_cards_json(snapshot), session_context=case.get('context'))
                    row['verified_model'] = MODEL if adapter_factory is None else 'mock'
                    # Retain schema-valid outputs even if grounding validation fails.
                    row['interpretation'] = interpretation.model_dump(mode='json')
                    row['extra_term_ids'] = sorted({item.term_id for item in interpretation.selections}
                        - set(case['expected'].get('required_terms', [])))
                    row['review_flags'] = ['extra_terms_require_semantic_review'] if row['extra_term_ids'] else []
                    resolution = await validate(SyntheticMemory(case), {'request_text': case['input']}, interpretation, snapshot)
                    row.update(status='completed', checks=check_output(case, interpretation),
                               resolution_status=resolution.status)
            except LLMConfigurationError:
                row.update(status='configuration_error', failure_code='CONFIGURATION_ERROR')
                stopped = True
            except LLMTimeout:
                row.update(status='timeout', failure_code='LLM_TIMEOUT')
            except LLMError as error:
                row.update(status='invalid_or_failed', failure_code=error.failure_code.value)
            except Exception:
                row.update(status='runner_error', failure_code='INTERNAL_CODE_ERROR')
                stopped = True
            row['latency_ms'] = round((time.monotonic()-started)*1000)
            row['passed_checks'] = bool(row['checks']) and all(row['checks'].values())
            output_file.write(json.dumps(row, ensure_ascii=False)+'\n')
            output_file.flush()
            print(f"{case['id']}: {row['status']}", flush=True)
    return info


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case-ids', required=True, help=','.join(CASE_IDS))
    parser.add_argument('--source-commit', required=True)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--execute', action='store_true', help='Consume ChatGPT subscription allowance; requires separate human authorization')
    args = parser.parse_args()
    try:
        asyncio.run(run(args.output, args.case_ids.split(','), args.source_commit, execute=args.execute))
    except Exception:
        raise SystemExit('Evaluation setup failed; check arguments and local files. No automatic retry.') from None


if __name__ == '__main__':
    main()
