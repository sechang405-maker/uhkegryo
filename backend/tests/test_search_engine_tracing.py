"""Acceptance tests for engine diagnostics and their trace/privacy boundary."""
import asyncio
import json
from types import SimpleNamespace

import pytest

from backend.schemas.enums import Role
from backend.services.job_trace import JobTracer
from backend.services.searxng_pinterest_search import SearXNGPinterestSearchProvider
from backend.tests.test_job_trace import FakeLangfuse
from backend.tests.test_parallel_role_search import setup, search, resolution, empty


@pytest.mark.parametrize("mode", ["success", "engine_error", "empty", "timeout", "malformed"])
def test_engine_attempts_match_actual_calls(mode):
    async def scenario():
        attempts, calls = [], []
        async def load(url, params):
            bang = params["q"].split()[0]
            calls.append(bang)
            if mode == "timeout":
                raise TimeoutError("secret upstream detail")
            if mode == "malformed":
                return {"secret": "do not trace"}
            if mode == "empty":
                return {"results": []}
            if mode == "engine_error":
                return {"results": [], "unresponsive_engines": [["pinterest", "access denied"]]}
            return {"results": [{"url": "https://pinterest.com/pin/123/"}]}
        out = await SearXNGPinterestSearchProvider(
            base_url="http://search", json_loader=load, engine_attempts=attempts,
        ).search(Role.POSE, ("standing",))
        assert [r["bang"] for r in attempts] == calls
        assert len(attempts) == 1
        assert all(r["latency_ms"] >= 0 for r in attempts)
        assert "secret" not in json.dumps(attempts)
        if mode == "success":
            assert attempts[0]["bang"] == "!pin" and attempts[0]["fallback"] is False
            assert attempts[0]["status"] == "success" and attempts[0]["pin_count"] == len(out.pins) == 1
        elif mode == "empty":
            assert all(r["status"] == "empty" for r in attempts)
        elif mode == "engine_error":
            assert attempts[0]["failure_reason"] == "access_denied"
            assert attempts[0]["fallback"] is False
        else:
            reason = "timeout" if mode == "timeout" else "malformed_response"
            assert all(r["failure_reason"] == reason for r in attempts)
    asyncio.run(scenario())


@pytest.mark.parametrize("text_response", [False, True])
def test_parallel_worker_attaches_diagnostics_to_job_and_removes_from_llm(monkeypatch, snapshot_factory, text_response):
    async def scenario():
        async def handler(name, args):
            await asyncio.sleep(0)
            payload = {**empty(args["role"]), "_search_trace": [{
                "engine": "pinterest", "bang": "!pin", "latency_ms": 12,
                "pin_count": 0, "status": "empty", "failure_reason": None, "fallback": False,
                "secret": "must not leave gateway",
            }]}
            return {"content": [{"type": "text", "text": json.dumps(payload)}]} if text_response else payload
        roles = ["pose", "view"]
        worker, adapter = setup(monkeypatch, snapshot_factory, [[search(r) for r in roles], []], handler)
        client = FakeLangfuse()
        worker._tracer = JobTracer(client)
        with worker._tracer.attempt({"job_id": "job", "session_id": "s", "attempt": 1,
                                    "max_attempts": 3, "request_text": "test"}):
            await worker._search_outcomes(resolution(roles), request_text="test")
        records = [r for r in client.records if r["name"].startswith("pinterest-search-")]
        assert {r["input"]["role"] for r in records} == set(roles)
        assert all(r["trace_id"] == "trace:job" for r in records)
        assert all(len(r["output"]["engine_attempts"]) == 1 for r in records)
        assert "secret" not in json.dumps(records)
        assert "_search_trace" not in json.dumps(adapter.tool_requests)
    asyncio.run(scenario())


def test_diagnostic_validation_and_observation_failure_are_nonfatal():
    client = FakeLangfuse()
    tracer = JobTracer(client)
    with tracer.search("pose", ["standing"]) as span:
        tracer.search_result(span, [{"engine": []}, {"engine": "pinterest"}])
    assert client.records[0]["output"] == {"engine_attempts": []}
    def broken(**kwargs):
        raise RuntimeError("telemetry down")
    tracer.search_result(SimpleNamespace(update=broken), None)
    tracer = JobTracer(SimpleNamespace(start_as_current_observation=broken))
    with tracer.search("pose", ["standing"]) as span:
        assert span is None
