"""Concurrency and lifecycle acceptance tests for parallel-role-search.md."""
import asyncio
import json
from time import perf_counter
from types import SimpleNamespace

import pytest

from backend.schemas.enums import FailureCode, Role
from backend.services import agent_worker
from backend.services.failure_mapping import OperationalFailure
from backend.tests.test_agent_worker import (
    FakeAdapter, FakeJobs, FakeMcpGateway, FakeRecovery, _worker,
)


def search(role, call_id=None, fragments=None):
    return {"id": call_id or role, "name": "search_pinterest_pins", "arguments": {
        "role": role, "query_fragments": fragments or [role],
    }}


def resolution(roles):
    return SimpleNamespace(terms=[SimpleNamespace(
        selection=SimpleNamespace(role=Role(role), term_id=role), card={"query_fragments": [role]},
    ) for role in roles])


def setup(monkeypatch, snapshot_factory, calls, handler, widget=None):
    gateway = FakeMcpGateway([])
    gateway.call_tool = handler
    adapter = FakeAdapter(tool_calls=calls)
    worker = _worker(monkeypatch, FakeJobs(), FakeRecovery(), snapshot_factory([]),
                     adapter, mcp_gateway=gateway, widget_client=widget)
    return worker, adapter


def empty(role):
    return {"role": role, "pins": [], "code": "PIN_RESULTS_EMPTY"}


def test_parallel_overlap_order_and_timing(monkeypatch, snapshot_factory):
    async def scenario():
        active = peak = 0
        finished = []

        async def handler(name, args):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            role = args["role"]
            await asyncio.sleep({"body": .06, "pose": .04, "view": .02}[role])
            active -= 1
            finished.append(role)
            return empty(role)

        roles = ["body", "pose", "view"]
        started = perf_counter()
        for role in roles:
            await handler("search_pinterest_pins", {"role": role})
        sequential = perf_counter() - started
        finished.clear()
        worker, adapter = setup(monkeypatch, snapshot_factory,
                                [[search(r) for r in roles], []], handler)
        started = perf_counter()
        outcomes = await worker._search_outcomes(resolution(roles), request_text="test")
        parallel = perf_counter() - started
        assert peak == 3 and finished != roles
        assert set(outcomes) == {Role(r) for r in roles}
        replies = [m for m in adapter.tool_requests[-1][0] if m["role"] == "tool"]
        assert [m["tool_call_id"] for m in replies] == roles
        assert [json.loads(m["content"])["role"] for m in replies] == roles
        assert parallel < sequential
        print(f"search fixture: sequential={sequential:.3f}s parallel={parallel:.3f}s")

    asyncio.run(scenario())


def test_shared_limit_includes_widget_across_jobs(monkeypatch, snapshot_factory):
    async def scenario():
        active = peak = started = 0
        occupied, release = asyncio.Event(), asyncio.Event()

        async def handler(name, args):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            return empty(args["role"])

        class Widget:
            async def enrich_outcome(self, outcome):
                nonlocal active, started
                started += 1
                if started == 3:
                    occupied.set()
                await release.wait()
                active -= 1
                return outcome

        roles = [r.value for r in Role]
        calls = [search(r) for r in roles]
        worker, _ = setup(monkeypatch, snapshot_factory, [calls, calls, [], []], handler, Widget())
        tasks = [asyncio.create_task(worker._search_outcomes(resolution(roles), request_text="test"))
                 for _ in range(2)]
        await asyncio.wait_for(occupied.wait(), 1)
        assert started == active == peak == 3
        release.set()
        results = await asyncio.wait_for(asyncio.gather(*tasks), 1)
        assert started == 10 and active == 0 and peak == 3
        assert all(len(result) == 5 for result in results)

    asyncio.run(scenario())


def test_validation_duplicates_and_nonsearch_boundaries(monkeypatch, snapshot_factory):
    async def scenario():
        events = []

        async def handler(name, args):
            role = args.get("role", "card")
            events.append(role + " start")
            await asyncio.sleep(0)
            events.append(role + " end")
            return empty(role) if role != "card" else {}

        calls = [search("body", "bad", ["invented"]), search("body", "valid"),
                 search("body", "duplicate"),
                 {"id": "card", "name": "get_active_term_card", "arguments": {}},
                 search("pose")]
        worker, adapter = setup(monkeypatch, snapshot_factory, [calls, []], handler)
        await worker._search_outcomes(resolution(["body", "pose"]), request_text="test")
        assert events == ["body start", "body end", "card start", "card end", "pose start", "pose end"]
        replies = [m for m in adapter.tool_requests[-1][0] if m["role"] == "tool"]
        assert [m["tool_call_id"] for m in replies] == [c["id"] for c in calls]
        assert "error" in json.loads(replies[0]["content"])
        assert "error" in json.loads(replies[2]["content"])

    asyncio.run(scenario())


def test_retry_backoff_releases_search_slots(monkeypatch, snapshot_factory):
    async def scenario():
        seen, delays = [], []

        async def handler(name, args):
            role = args["role"]
            seen.append(role)
            if role == "pose" and seen.count(role) == 1:
                raise RuntimeError("search upstream unavailable")
            if role == "view":
                return {"role": role, "pins": [{"pin_id": "123",
                        "pin_url": "https://www.pinterest.com/pin/123/", "status": "available"}], "code": None}
            return {"role": role, "pins": [], "code": "PIN_SEARCH_UNAVAILABLE"} if role == "pose" else empty(role)

        worker, _ = setup(monkeypatch, snapshot_factory,
                          [[search("body"), search("pose"), search("pose", "duplicate"), search("view")],
                           [search("pose")], [search("pose")], []], handler)

        async def backoff(delay):
            delays.append(delay)
            # All three places remain usable by another Job during backoff.
            for _ in range(3):
                await asyncio.wait_for(worker._search_slots.acquire(), .5)
            for _ in range(3):
                worker._search_slots.release()

        monkeypatch.setattr(agent_worker.asyncio, "sleep", backoff)
        outcomes = await worker._search_outcomes(resolution(["body", "pose", "view"]), request_text="test")
        assert seen.count("body") == 1 and seen.count("pose") == 3
        assert seen.count("view") == 1 and outcomes[Role.VIEW].pins[0].pin_id == "123"
        assert delays == [1, 2]
        assert outcomes[Role.BODY].code.value == "PIN_RESULTS_EMPTY"
        assert outcomes[Role.POSE].code.value == "PIN_SEARCH_UNAVAILABLE"

    asyncio.run(scenario())


@pytest.mark.parametrize("abort", ["configuration", "cancel"])
def test_abort_cleans_running_and_queued_searches(monkeypatch, snapshot_factory, abort):
    async def scenario():
        started, finished = [], []
        occupied = asyncio.Event()

        async def handler(name, args):
            role = args["role"]
            started.append(role)
            if len(started) == 3:
                occupied.set()
            try:
                await occupied.wait()
                if abort == "configuration" and role == "body":
                    raise OperationalFailure(FailureCode.CONFIGURATION_ERROR)
                await asyncio.Future()
            finally:
                finished.append(role)

        roles = [r.value for r in Role]
        worker, _ = setup(monkeypatch, snapshot_factory, [[search(r) for r in roles]], handler)
        task = asyncio.create_task(worker._search_outcomes(resolution(roles), request_text="test"))
        await asyncio.wait_for(occupied.wait(), 1)
        if abort == "cancel":
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            with pytest.raises(OperationalFailure) as error:
                await task
            assert error.value.failure_code is FailureCode.CONFIGURATION_ERROR
        assert set(started) == set(finished)
        for _ in range(3):
            await asyncio.wait_for(worker._search_slots.acquire(), .5)

    asyncio.run(scenario())
