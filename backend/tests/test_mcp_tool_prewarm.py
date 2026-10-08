"""Worker startup and periodic MCP tool discovery."""

import asyncio
from types import SimpleNamespace

import pytest

from backend.services import agent_worker
from backend.services.agent_worker import AgentJobWorker
from backend.services.mcp_tool_gateway import McpToolGateway


async def _idle_task(*args):
    await asyncio.Future()


def test_worker_prewarms_before_claiming_jobs(monkeypatch, snapshot_factory):
    async def case():
        listed, release, polled = asyncio.Event(), asyncio.Event(), asyncio.Event()
        calls = []

        async def operation(url, action, **kwargs):
            calls.append(action)
            listed.set()
            await release.wait()
            return SimpleNamespace(tools=[{"name": "lookup", "inputSchema": {"type": "object"}}])

        gateway = McpToolGateway(mcp_url="http://mcp/mcp", operation_caller=operation)
        worker = AgentJobWorker(None, snapshot_factory([]), mcp_gateway=gateway,
                                tracer=SimpleNamespace(shutdown=lambda: None))
        async def run_once():
            polled.set()
            await gateway.list_tools()
            return False
        monkeypatch.setattr(worker, "run_once", run_once)
        monkeypatch.setattr(worker._recovery, "recover_expired_leases", _idle_task)
        task = asyncio.create_task(worker.run_forever(concurrency=1))
        try:
            await asyncio.wait_for(listed.wait(), 1)
            assert not polled.is_set(), "job polling started before MCP discovery finished"
            release.set()
            await asyncio.wait_for(polled.wait(), 1)
            assert calls == ["list_tools"]
        finally:
            release.set()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
    asyncio.run(case())


def test_worker_refreshes_periodically_and_cancels_refresh(monkeypatch, snapshot_factory):
    async def case():
        refresh_started, refresh_stopped = asyncio.Event(), asyncio.Event()
        calls = 0
        sleep_delays = []

        async def record_sleep(seconds):
            sleep_delays.append(seconds)

        async def operation(url, action, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 3:
                refresh_started.set()
                try:
                    await asyncio.Future()
                finally:
                    refresh_stopped.set()
            return SimpleNamespace(tools=[{
                "name": f"lookup_{calls}", "inputSchema": {"type": "object"}
            }])

        monkeypatch.setattr(agent_worker.asyncio, "sleep", record_sleep)
        worker = AgentJobWorker(None, snapshot_factory([]),
                                mcp_gateway=McpToolGateway(mcp_url="http://mcp/mcp", operation_caller=operation),
                                tracer=SimpleNamespace(shutdown=lambda: None))
        monkeypatch.setattr(worker._recovery, "recover_expired_leases", _idle_task)
        task = asyncio.create_task(worker.run_forever(concurrency=0))
        try:
            await asyncio.wait_for(refresh_started.wait(), 1)
            assert [tool["name"] for tool in await worker._mcp_gateway.list_tools()] == ["lookup_2"]
        finally:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        assert calls == 3
        assert sleep_delays == [10800, 10800]
        assert refresh_stopped.is_set()
    asyncio.run(case())


def test_failed_periodic_refresh_retries_without_stopping_worker(monkeypatch, snapshot_factory):
    async def case():
        recovered = asyncio.Event()
        calls = 0

        async def operation(url, action, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("temporary MCP failure")
            if calls == 3:
                recovered.set()
            return SimpleNamespace(tools=[{"name": f"lookup_{calls}",
                                           "inputSchema": {"type": "object"}}])

        monkeypatch.setattr(agent_worker, "MCP_TOOL_REFRESH_INTERVAL_SECONDS", .01)
        gateway = McpToolGateway(mcp_url="http://mcp/mcp", operation_caller=operation)
        worker = AgentJobWorker(None, snapshot_factory([]), mcp_gateway=gateway,
                                tracer=SimpleNamespace(shutdown=lambda: None))
        monkeypatch.setattr(worker._recovery, "recover_expired_leases", _idle_task)
        task = asyncio.create_task(worker.run_forever(concurrency=0))
        try:
            await asyncio.wait_for(recovered.wait(), 1)
            assert not task.done()
            assert [tool["name"] for tool in await gateway.list_tools()] == ["lookup_3"]
        finally:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
    asyncio.run(case())


@pytest.mark.parametrize("failure", ["error", "timeout"])
def test_failed_prewarm_does_not_block_polling(monkeypatch, snapshot_factory, failure):
    async def case():
        polled = asyncio.Event()
        calls = 0
        async def operation(url, action, **kwargs):
            nonlocal calls
            calls += 1
            if failure == "timeout":
                await asyncio.Future()
            raise RuntimeError("remote unavailable")
        monkeypatch.setattr(agent_worker, "MCP_TOOL_REFRESH_TIMEOUT_SECONDS", .01)
        worker = AgentJobWorker(None, snapshot_factory([]),
                                mcp_gateway=McpToolGateway(mcp_url="http://mcp/mcp", operation_caller=operation),
                                tracer=SimpleNamespace(shutdown=lambda: None))
        async def run_once():
            polled.set()
            return False
        monkeypatch.setattr(worker, "run_once", run_once)
        monkeypatch.setattr(worker._recovery, "recover_expired_leases", _idle_task)
        task = asyncio.create_task(worker.run_forever(concurrency=1))
        try:
            await asyncio.wait_for(polled.wait(), 1)
            assert calls == 1
        finally:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
    asyncio.run(case())
