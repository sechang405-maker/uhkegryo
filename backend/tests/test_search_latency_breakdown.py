"""Acceptance coverage for search-latency-breakdown.md."""
import asyncio
import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.routes import agent as route
from backend.schemas.enums import JobStatus, Role
from backend.services import agent_worker
from backend.services.job_repository import JobNotFound
from backend.services.job_trace import JobTracer
from backend.services.pinterest_widget import PinterestWidgetClient
from backend.shared.auth import SESSION_COOKIE_NAME
from backend.tests.test_job_trace import FakeLangfuse, _job
from backend.tests.test_parallel_role_search import setup, search, resolution, empty
from backend.tests.test_pinterest_widget import _completed_job, _payload


def test_parallel_phases_and_generation_purpose(monkeypatch, snapshot_factory):
    async def run():
        async def handler(name, args):
            await asyncio.sleep(.002)
            return {**empty(args["role"]), "pins": [{"pin_id": pin,
                    "pin_url": f"https://pinterest.com/pin/{pin}/", "status": "available"}
                   for pin in ("11", "22")], "code": None, "_search_trace": [{
                       "engine": "pinterest", "bang": "!pin", "latency_ms": 1,
                       "pin_count": 2, "status": "success", "failure_reason": None, "fallback": False}]}

        async def widget(url):
            await asyncio.sleep(.002)
            return _payload("11", {"image": {"url": "https://private-thumbnail/image.jpg",
                                             "width": 10, "height": 10}})

        worker, adapter = setup(monkeypatch, snapshot_factory,
                                [[search("pose"), search("view")]] * 2 + [[], []], handler,
                                PinterestWidgetClient(json_loader=widget))
        client = FakeLangfuse()
        worker._tracer = JobTracer(client)
        original = adapter.request_mcp_tool_calls

        async def generate(*args, **kwargs):
            with client.start_as_current_observation(as_type="generation", name="existing-generation"):
                return await original(*args, **kwargs)

        adapter.request_mcp_tool_calls = generate
        async def execute(job_id):
            with worker._tracer.attempt(_job(1, job_id)):
                return await worker._search_outcomes(resolution(["pose", "view"]), request_text="private request")
        outcomes = (await asyncio.gather(execute("job-1"), execute("job-2")))[0]
        records = client.records
        assert {r["trace_id"] for r in records} == {"trace:job-1", "trace:job-2"}
        for trace_id in ("trace:job-1", "trace:job-2"):
            assert {r["metadata"]["role"] for r in records
                    if r["trace_id"] == trace_id and r["name"] == "mcp-search-call"} == {"pose", "view"}
        selection = next(r for r in records if r["name"] == "mcp-tool-selection")
        assert selection["metadata"] == {"call_round": 1, "purpose": "tool_selection", "pending_roles": ["pose", "view"]}
        assert selection["output"]["selected_roles"] == ["pose", "view"]
        final = next(r for r in records if r["name"] == "mcp-post-search-decision")
        assert final["metadata"]["call_round"] == 2 and final["output"]["call_count"] == 0
        for name in ("search-slot-wait", "mcp-search-call", "widget-enrichment"):
            spans = [r for r in records if r["name"] == name]
            assert {r["metadata"]["role"] for r in spans} == {"pose", "view"}
            assert all(r["metadata"]["search_attempt"] == 1 and r["output"]["elapsed_ms"] >= 0 for r in spans)
        widgets = [r for r in records if r["name"] == "widget-enrichment"]
        assert all(r["output"]["available_count"] == r["output"]["unavailable_count"] == 1 for r in widgets)
        assert all(len(r["output"]["engine_attempts"]) == 1 for r in records if r["name"].startswith("pinterest-search-"))
        assert len(outcomes[Role.POSE].pins) == 2
        assert "private-thumbnail" not in json.dumps(records) and "private request" not in json.dumps(records)
        assert "_search_trace" not in json.dumps(adapter.tool_requests)

    asyncio.run(run())


def test_retry_failure_and_invalid_role_do_not_break_observation(monkeypatch, snapshot_factory):
    async def run():
        count = 0

        async def handler(name, args):
            nonlocal count
            count += 1
            if count == 1:
                raise RuntimeError("private upstream detail")
            return {**empty("pose"), "code": "PIN_SEARCH_UNAVAILABLE"}

        async def sleep(delay):
            assert delay in (1, 2)

        monkeypatch.setattr(agent_worker.asyncio, "sleep", sleep)
        bad = search("pose", "bad")
        bad["arguments"]["role"] = []
        worker, _ = setup(monkeypatch, snapshot_factory,
                          [[bad, search("pose")], [search("pose")], [search("pose")], []], handler)
        client = FakeLangfuse()
        worker._tracer = JobTracer(client)
        await worker._search_outcomes(resolution(["pose"]), request_text="test")
        retries = [r for r in client.records if r["name"] == "search-retry-wait"]
        assert [r["metadata"]["search_attempt"] for r in retries] == [1, 2]
        assert [r["output"]["planned_ms"] for r in retries] == [1000, 2000]
        assert [r["output"]["reason"] for r in retries] == ["tool_error", "pin_search_unavailable"]
        failed = next(r for r in client.records if r["name"] == "mcp-search-call")
        assert failed["output"]["status"] == "interrupted" and failed["output"]["error_type"] == "RuntimeError"
        assert "private upstream detail" not in json.dumps(client.records) and count == 3

    asyncio.run(run())


def test_cancelled_slot_wait_records_time(monkeypatch, snapshot_factory):
    async def run():
        async def forbidden(*args):
            pytest.fail("cancelled wait must not call MCP")

        worker, _ = setup(monkeypatch, snapshot_factory, [[search("pose")]], forbidden)
        client = FakeLangfuse()
        worker._tracer = JobTracer(client)
        for _ in range(3):
            await worker._search_slots.acquire()
        with worker._tracer.attempt(_job(1)):
            task = asyncio.create_task(worker._search_outcomes(resolution(["pose"]), request_text="test"))
            for _ in range(5):
                await asyncio.sleep(0)
                if any(r["name"] == "search-slot-wait" for r in client.records):
                    break
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        wait = next(r for r in client.records if r["name"] == "search-slot-wait")
        assert wait["output"]["status"] == "interrupted" and wait["output"]["elapsed_ms"] >= 0
        assert wait["trace_id"] == "trace:job-1"

    asyncio.run(run())


@pytest.mark.parametrize("state", ["queued", "completed", "denied", "missing_cookie"])
def test_result_api_omits_polling_trace_and_preserves_ownership_and_counts(monkeypatch, state):
    stored = _completed_job()
    if state == "queued":
        stored.job_status, stored.result, stored.poll_after_ms = JobStatus.QUEUED, None, 1000
    client_trace = FakeLangfuse()
    monkeypatch.setattr(route, "get_result_tracer", lambda: JobTracer(client_trace))

    class Sessions:
        async def has_owner(self, token):
            return token == "private-token"
        async def session_for_job(self, token, job_id):
            if state == "denied":
                raise JobNotFound
            return "session-1"

    async def get(**kwargs):
        return stored
    async def repositories():
        return Sessions(), SimpleNamespace(get=get)
    async def widget(url):
        return _payload("11", {"image": {"url": "https://private-thumbnail/image.jpg", "width": 10, "height": 10}})

    monkeypatch.setattr(route, "get_repositories", repositories)
    monkeypatch.setattr(route, "get_widget_client", lambda: PinterestWidgetClient(json_loader=widget))
    with TestClient(app) as client:
        if state != "missing_cookie":
            client.cookies.set(SESSION_COOKIE_NAME, "private-token")
        for _ in range(3):
            response = client.get("/api/jobs/00000000-0000-0000-0000-000000000001")
    if state in ("denied", "missing_cookie"):
        assert response.status_code == (404 if state == "denied" else 401)
        assert not client_trace.records
        return
    assert response.status_code == 200 and response.json()["job_status"] == state
    assert not any(r["name"] == "job-result-read" for r in client_trace.records)
    assert len(client_trace.records) == (3 if state == "completed" else 0)
    if state == "completed":
        assert all(r["name"] == "result-widget-refresh" for r in client_trace.records)
        assert all(r["trace_id"] == "trace:00000000-0000-0000-0000-000000000001"
                   and r["output"]["available_count"] == 1 for r in client_trace.records)
        assert response.json()["result"]["reference_plan"]["terms"][0]["pins"][0]["thumbnail_url"] is not None
        assert stored.result.reference_plan.terms[0].pins[0].thumbnail_url is None
    assert all(value not in json.dumps(client_trace.records) for value in ("private-token", "private-thumbnail"))


@pytest.mark.parametrize("failure", ["start", "update"])
def test_telemetry_failure_is_nonfatal(failure):
    def broken(**kwargs):
        raise RuntimeError("private telemetry detail")

    client = FakeLangfuse()
    if failure == "start":
        client.start_as_current_observation = broken
    else:
        original = client.start_as_current_observation
        from contextlib import contextmanager
        @contextmanager
        def observe(**kwargs):
            with original(**kwargs):
                yield SimpleNamespace(update=broken)
        client.start_as_current_observation = observe
    with JobTracer(client).result_read("job", "session") as metrics:
        metrics["job_status"] = "completed"
    assert metrics["status"] == "completed"
    assert not client.records


def test_result_tracer_reuse_and_lifespan_shutdown(monkeypatch):
    client, calls = FakeLangfuse(), []
    client.shutdown = lambda: calls.append("shutdown")
    tracer = JobTracer(client)
    monkeypatch.setattr(route, "_result_tracer", None)
    monkeypatch.setattr(JobTracer, "from_settings", lambda: calls.append("create") or tracer)
    with TestClient(app):
        assert route.get_result_tracer() is route.get_result_tracer() is tracer
        assert calls == ["create"]
    assert calls == ["create", "shutdown"] and route._result_tracer is None
