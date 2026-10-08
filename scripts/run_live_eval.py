"""Run the fixed 30 cases with real LLM/worker/PostgreSQL and fixture search."""
import asyncio
import hashlib
import json
import math
import os
import subprocess
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import asyncpg
from pydantic import ValidationError

from backend.schemas.enums import JobStatus, ReasonCode
from backend.schemas.models import PinResult
from backend.services.agent_worker import AgentJobWorker
from backend.services.catalog_repository import load_catalog
from backend.services.job_repository import JobRepository
from backend.services.job_retry_recovery import JobRetryRecovery
from backend.services.job_trace import JobTracer
from backend.services.llm import LLMInterpretationAdapter, LLMInvalidStructuredOutput
from backend.services.response_assembler import RoleSearchOutcome
from backend.services.session_repository import SessionRepository
from backend.shared.config import Settings

ROOT = Path(__file__).resolve().parents[1]
_OUTPUT_FIELDS = frozenset({"interpretation_state", "selections", "unresolved_constraints", "clarifying_question",
                            "clarification_type", "context_updates", "role", "term_id", "evidence",
                            "confidence", "source_job_id", "keywords", "mode", "answer_text"})


def _safe_validation_path(location):
    parts = ["[]" if isinstance(part, int) else part if isinstance(part, str) and part in _OUTPUT_FIELDS
             else "unknown_field" for part in location[:12]]
    return (".".join(parts) or "unknown_field")[:96]


class MeasuredAdapter(LLMInterpretationAdapter):
    def reset(self, case):
        self.case, self.calls, self.outputs, self.validation_failures = case, [], [], []

    def record_validation_failure(self, error, *, attempt):
        cause = error.__cause__
        detail = None
        if isinstance(cause, json.JSONDecodeError):
            code = "json_syntax"
        elif isinstance(cause, ValidationError):
            code = "output_schema"
            first = cause.errors(include_input=True)[0]
            detail = {"field": _safe_validation_path(first["loc"]),
                      "type": str(first["type"])[:64]}
        elif cause is not None:
            code = "output_schema"
        else:
            message = str(error)
            if "선택 근거" in message or "선택 출처" in message:
                code = "selection_evidence"
            elif "조건 변경" in message:
                code = "context_evidence"
            elif "카드" in message or "카탈로그" in message:
                code = "catalog_validation"
            elif "evaluation fixture" in message:
                code = "injected_failure"
            else:
                code = "other_validation"
        repair_codes = [item.get("code") for item in error.feedback
                        if item.get("code") in {"role_duplicate", "role_order", "state_rules"}]
        if repair_codes:
            code = repair_codes[0]
        item = {"attempt": attempt, "code": code}
        if detail:
            item["detail"] = detail
        self.validation_failures.append(item)

    async def _request(self, messages, *, output_format=None):
        started = time.monotonic()
        response = await super()._request(messages, output_format=output_format)
        usage = response.usage.model_dump() if response.usage else {}
        self.calls.append({"latency_ms": round((time.monotonic() - started) * 1000),
                           "response_model": response.model,
                           "input_tokens": usage.get("prompt_tokens", 0),
                           "output_tokens": usage.get("completion_tokens", 0),
                           "cost_usd": usage.get("cost")})
        return response

    async def interpret(self, *args, **kwargs):
        if self.case["runtime_fixture"].get("llm_sequence") and kwargs["attempt"] == 1:
            raise LLMInvalidStructuredOutput("evaluation fixture: invalid structured output")
        output = await super().interpret(*args, **kwargs)
        self.outputs.append(output.model_dump(mode="json"))
        return output


class FixtureSearch:
    def __init__(self, fixture):
        self.fixture, self.calls = fixture, []

    async def search(self, role, query_fragments):
        self.calls.append({"role": role.value, "query_fragments": list(query_fragments)})
        mode = self.fixture.get("pinterest_search", "success")
        config = mode if isinstance(mode, dict) else {"result": mode}
        kind = config["result"]
        code = {"empty": ReasonCode.PIN_RESULTS_EMPTY,
                "timeout_after_retries": ReasonCode.PIN_SEARCH_UNAVAILABLE}.get(kind)
        if code:
            return RoleSearchOutcome(role, code=code)
        deleted = kind == "success_with_deleted_pin"
        pins = [PinResult(pin_id=f"fixture-{role.value}-{i}",
                          pin_url=f"https://www.pinterest.com/pin/{100000+i}/",
                          status="deleted" if deleted else "available")
                for i in range(config.get("available_pin_count", 1))]
        return RoleSearchOutcome(role, pins)


class FixtureSearchWorker(AgentJobWorker):
    """Keep production job execution; exclude MCP tool selection from this eval."""
    async def _search_outcomes(self, resolution, *, request_text):
        return {term.selection.role: await self.fixture_search.search(
            term.selection.role, term.card["query_fragments"])
            for term in resolution.terms}


def question_addresses(contract, question):
    """Bounded cue checks, not a semantic-quality grade."""
    clues = contract.get("must_address", "") + " ".join(contract.get("must_address_any_of", []))
    if "겉실루엣" in clues:
        return all(word in question for word in ("의상", "실제", "체형", "겉실루엣"))
    if "어깨와 골반" in clues:
        return all(word in question for word in ("어깨", "골반", "비슷", "넓", "우선"))
    if "옆모습" in clues:
        return all(word in question for word in ("옆모습", "정면", "우선"))
    if "한쪽 다리" in clues:
        return ("한쪽 다리" in question and "체중" in question) or ("S" in question and "몸통" in question)
    return False


def assess(case, submitted, terminal, searches):
    expected = case["expected"]
    result = terminal.get("result") or {}
    plan = result.get("reference_plan")
    terms = (plan or {}).get("terms", [])
    selected = {(t["role"], t["term_id"]) for t in terms}
    required = {(t["role"], t["term_id"]) for t in expected.get("required_selections", [])}
    checks = {"submission_envelope": submitted["job_status"] == "queued" and submitted["poll_after_ms"] == 1000,
              "terminal_status": terminal["job_status"] == expected["terminal"]["job_status"],
              "required_selections": required <= selected,
              "forbidden_selections": not ({t[1] for t in selected} & set(expected.get("forbidden_term_ids", []))),
              "reference_plan": bool(plan) == expected["reference_plan"]["present"],
              "pin_limit": all(len(t["pins"]) <= 8 for t in terms)}
    for key in ("agent_status", "reason_codes"):
        if key in expected["terminal"]:
            checks[key] = result.get(key) == expected["terminal"][key]
    if "failure" in expected["terminal"]:
        checks["failure_code"] = (terminal.get("failure") or {}).get("failure_code") == expected["terminal"]["failure"]["failure_code"]
    if "attempt" in expected:
        checks["attempt"] = terminal["attempt"] == expected["attempt"]["final"]
    if "attempt" in expected["terminal"]:
        checks["attempt"] = terminal["attempt"] == expected["terminal"]["attempt"]["final"]
    reference = expected["reference_plan"]
    if "pin_statuses" in reference:
        checks["pin_statuses"] = [p["status"] for t in terms for p in t["pins"]] == reference["pin_statuses"]
    if "pins_empty_for_roles" in reference:
        checks["empty_pins"] = all(not t["pins"] for t in terms if t["role"] in reference["pins_empty_for_roles"])
    if "search" not in expected["tool_calls"]:
        checks["no_search"] = not searches
    if "clarifying_question" in expected:
        question = result.get("clarifying_question") or ""
        checks["question_count"] = question.count("?") == expected["clarifying_question"]["count"]
        checks["question_domain_cues"] = question_addresses(expected["clarifying_question"], question)
    return checks


async def execute(case, pool, snapshot, adapter):
    sessions, jobs = SessionRepository(pool), JobRepository(pool)
    sid = await sessions.create_session(uuid.uuid4().hex)
    if case["id"] == "EVAL-27":
        previous, _ = await jobs.submit(session_id=sid, request_text="마른 체형으로 두 발로 똑바로 서 있는 캐릭터를 찾아줘", idempotency_key=uuid.uuid4().hex)
        seed = {"agent_status": "success", "reference_plan": {"terms": [
            {"role": "body", "term_id": "body_slim", "label_ko": "마른 체형", "label_en": "slim"},
            {"role": "pose", "term_id": "pose_standing", "label_ko": "서기", "label_en": "standing"}]}}
        await pool.execute("UPDATE jobs SET status='completed', succeeded=true, final_payload_json=$2::jsonb, completed_at=now() WHERE job_id=$1", previous.job_id, json.dumps(seed))
    submitted, _ = await jobs.submit(session_id=sid, request_text=case["input"], idempotency_key=uuid.uuid4().hex)
    adapter.reset(case)
    search = FixtureSearch(case["runtime_fixture"])
    worker = FixtureSearchWorker(pool, snapshot, adapter=adapter, tracer=JobTracer())
    worker.fixture_search = search
    recovery = JobRetryRecovery(pool)
    started = time.monotonic()
    while True:
        if case["runtime_fixture"].get("worker"):
            claimed = await jobs.claim_next()
            await pool.execute("UPDATE jobs SET lease_expires_at=now()-interval '1 second' WHERE job_id=$1", claimed["job_id"])
            await recovery.recover_expired_leases()
        else:
            worked = await worker.run_once()
            if not worked:
                await asyncio.sleep(0.25)
        terminal = await jobs.get(session_id=sid, job_id=str(submitted.job_id))
        if terminal.job_status in (JobStatus.COMPLETED, JobStatus.FAILED):
            break
    terminal_data = terminal.model_dump(mode="json")
    checks = assess(case, submitted.model_dump(mode="json"), terminal_data, search.calls)
    return {"id": case["id"], "category": case["category"], "input": case["input"],
            "fixture": case["runtime_fixture"], "submission": submitted.model_dump(mode="json"),
            "terminal": terminal_data, "interpretations": adapter.outputs, "calls": adapter.calls,
            "validation_failures": adapter.validation_failures,
            "search_calls": search.calls, "latency_ms": round((time.monotonic()-started)*1000),
            "checks": checks, "passed": all(checks.values()), "qualitative_score": None}


def report(directory, metadata, rows):
    passed = sum(r["passed"] for r in rows)
    latency = sorted(r["latency_ms"] for r in rows)
    calls = [c for r in rows for c in r["calls"]]
    total_tokens = sum(c["input_tokens"]+c["output_tokens"] for c in calls)
    lines = [f"# 실제 모델 {len(rows)}건 평가", "", f"- 실행: {metadata['started_kst']}",
             f"- 모델: `{metadata['model']}` / 카탈로그: `{metadata['catalog_version']}`",
             f"- 검사한 기대값 일치: **{passed}/{len(rows)}**", f"- 실제 모델 응답: {len(calls)}회 / 총 토큰: {total_tokens}",
             f"- 문항 지연 p50/p95: {latency[(len(rows)-1)//2]/1000:.2f}s / {latency[math.ceil(len(rows)*0.95)-1]/1000:.2f}s",
             "- 정성 점수: 지정 도메인 평가자와 독립 검토자 검토 전, 미산정.",
             "- 실제 PostgreSQL·worker·adapter·resolver·assembler 실행. 검색 단계는 평가 subclass의 fixture이며 MCP tool 선택은 미검사.",
             "- 질문 도메인 단서는 최종 서버 질문의 제한된 단어 조합으로 검사한다. 의미 품질·쉬운 언어는 별도 검토한다.",
             "- 미검사: HTTP 202·cookie 인증·MCP 네트워크/provenance·실제 Pinterest·Langfuse 전송·정성 품질. 전체 계약 준수율이 아님.",
             "", "| 문항 | 판정 | 실제 상태 | 불일치 검사 |", "|---|---|---|---|"]
    for row in rows:
        actual = row["terminal"].get("result") or row["terminal"].get("failure") or {}
        lines.append(f"| {row['id']} | {'PASS' if row['passed'] else 'FAIL'} | {actual.get('agent_status', actual.get('failure_code'))} | {', '.join(k for k,v in row['checks'].items() if not v) or '-'} |")
    costs = [c["cost_usd"] for c in calls]
    lines.append(f"\n제공자가 응답에 기록한 총 비용(USD): {sum(costs) if costs and all(c is not None for c in costs) else '미확인'}")
    (directory / "report.md").write_text("\n".join(lines)+"\n", encoding="utf-8")
    review = ["# 실제 사용자 답변 검토", "", "자동 정성 점수 아님. 의미·근거·관찰 지점과 질문의 충분성을 독립 검토한다.", ""]
    for row in rows:
        result = row["terminal"].get("result") or {}
        review += [f"## {row['id']} ({'PASS' if row['passed'] else 'FAIL'})", "", row["input"], "",
                   result.get("answer_text") or result.get("clarifying_question") or result.get("user_message") or "답변 없음", ""]
    (directory / "review.md").write_text("\n".join(review), encoding="utf-8")


async def main():
    settings = Settings()
    if not settings.openrouter_api_key or not settings.database_url.startswith(("postgres://", "postgresql://")):
        raise RuntimeError("OpenRouter key and PostgreSQL configuration required")
    settings.interpreter_prompt_path = str(Path(settings.interpreter_prompt_path).resolve())
    settings.langfuse_public_key = settings.langfuse_secret_key = ""
    dataset = ROOT / "evals/dataset.jsonl"
    cases = [json.loads(line) for line in dataset.read_text(encoding="utf-8").splitlines()]
    assert len(cases) == len({c["id"] for c in cases}) == 30
    extra_dataset = ROOT / "evals/ambiguity.jsonl"
    if os.getenv("LIVE_EVAL_INCLUDE_AMBIGUITY") == "1":
        cases += [json.loads(line) for line in extra_dataset.read_text(encoding="utf-8").splitlines()]
        assert len(cases) == len({case["id"] for case in cases})
    selected_ids = [x.strip() for x in os.getenv("LIVE_EVAL_CASE_IDS", "").split(",") if x.strip()]
    if selected_ids:
        known_ids = {case["id"] for case in cases}
        if len(selected_ids) != len(set(selected_ids)) or not set(selected_ids) <= known_ids:
            raise ValueError("LIVE_EVAL_CASE_IDS contains duplicate or unknown IDs")
        cases = [case for case in cases if case["id"] in selected_ids]
    snapshot = load_catalog(ROOT / "docs/domains/illustration-reference/term-cards")
    started = datetime.now(timezone(timedelta(hours=9)))
    model_slug = settings.llm_model.replace("/", "-").replace(":", "-")
    directory = ROOT / "evals/runs" / (started.strftime("%Y%m%d-%H%M%S")+"-"+model_slug)
    directory.mkdir(parents=True, exist_ok=False)
    digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    metadata = {"started_kst": started.isoformat(), "model": settings.llm_model,
                "prompt_version": settings.interpreter_prompt_version,
                "selected_case_ids": [case["id"] for case in cases],
                "dataset_sha256": digest(dataset), "prompt_sha256": digest(Path(settings.interpreter_prompt_path)),
                "adapter_sha256": digest(ROOT / "backend/services/llm.py"), "catalog_version": snapshot.dataset_version,
                "git_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
                "working_tree_dirty": bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT)),
                "temperature": 0, "max_tokens": settings.llm_max_tokens, "timeout_seconds": settings.llm_timeout_seconds,
                "langfuse": "disabled", "search": "fixture", "http": "not tested",
                "mcp_tool_selection": "not tested; evaluation worker overrides search stage"}
    sources = [p for folder in ("backend", "prompts", "skills", "scripts") for p in (ROOT / folder).rglob("*")
               if p.suffix in (".py", ".sql", ".md") and "__pycache__" not in p.parts]
    sources += [dataset, extra_dataset] if os.getenv("LIVE_EVAL_INCLUDE_AMBIGUITY") == "1" else [dataset]
    metadata["source_sha256"] = {str(p.relative_to(ROOT)): digest(p) for p in sorted(sources)}
    (directory / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    schema = "live_eval_" + uuid.uuid4().hex
    # Neon transaction pooling cannot preserve session search_path. Use its
    # direct endpoint for this isolated run and verify every acquired connection.
    parts = urlsplit(settings.database_url)
    database_url = settings.database_url
    if parts.hostname and parts.hostname.endswith("neon.tech"):
        database_url = urlunsplit(parts._replace(netloc=parts.netloc.replace("-pooler.", ".")))
    admin = await asyncpg.connect(database_url)
    pool, adapter, created = None, None, False
    rows = []
    try:
        await admin.execute(f'CREATE SCHEMA "{schema}"')
        created = True
        async def setup(connection):
            await connection.execute(f'SET search_path TO "{schema}"')
            if await connection.fetchval("SELECT current_schema()") != schema:
                raise RuntimeError("evaluation schema isolation failed")

        pool = await asyncpg.create_pool(database_url, min_size=1, max_size=4,
                                        server_settings={"search_path": schema}, setup=setup)
        for migration in sorted((ROOT / "backend/db/migrations").glob("*.sql")):
            await pool.execute(migration.read_text(encoding="utf-8"))
        adapter = MeasuredAdapter(settings=settings)
        for case in cases:
            row = await execute(case, pool, snapshot, adapter)
            rows.append(row)
            with (directory / "results.jsonl").open("a", encoding="utf-8") as output:
                output.write(json.dumps(row, ensure_ascii=False)+"\n")
            report(directory, metadata, rows)
            print(f"{row['id']}: {'PASS' if row['passed'] else 'FAIL'} ({len(row['calls'])} real calls)", flush=True)
    finally:
        if adapter:
            await adapter._client.close()
        if pool:
            await pool.close()
        if created:
            await admin.execute(f'DROP SCHEMA "{schema}" CASCADE')
        await admin.close()
    print(str(directory), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
