"""Generic MCP tool discovery and execution boundary."""

import asyncio
from types import SimpleNamespace

import pytest

from backend.services.mcp_tool_gateway import McpToolGateway
from backend.schemas.enums import FailureCode
from backend.services.failure_mapping import OperationalFailure


def test_lists_mcp_tool_schema_and_calls_listed_tool():
    calls = []

    async def operation(url, operation, name=None, arguments=None):
        calls.append((operation, name, arguments))
        if operation == "list_tools":
            return SimpleNamespace(tools=[{
                "name": "lookup", "description": "Look up a card",
                "inputSchema": {"type": "object", "properties": {"term_id": {"type": "string"}}, "required": ["term_id"]},
            }])
        return SimpleNamespace(isError=False, structuredContent={"status": "found"}, content=[])

    gateway = McpToolGateway(mcp_url="http://mcp:8001/mcp", operation_caller=operation)
    tools = asyncio.run(gateway.list_tools())
    result = asyncio.run(gateway.call_tool("lookup", {"term_id": "pose_x"}))

    assert tools == [{
        "name": "lookup", "description": "Look up a card",
        "inputSchema": {"type": "object", "properties": {"term_id": {"type": "string"}}, "required": ["term_id"]},
    }]
    assert result == {"status": "found"}
    assert calls[-1] == ("call_tool", "lookup", {"term_id": "pose_x"})


def test_rejects_unlisted_tool_and_arguments_outside_schema():
    async def operation(url, operation, name=None, arguments=None):
        return SimpleNamespace(tools=[{
            "name": "lookup", "description": "Look up a card",
            "inputSchema": {"type": "object", "properties": {"term_id": {"type": "string"}}, "required": ["term_id"], "additionalProperties": False},
        }])

    gateway = McpToolGateway(mcp_url="http://mcp:8001/mcp", operation_caller=operation)
    asyncio.run(gateway.list_tools())

    with pytest.raises(ValueError, match="not listed"):
        asyncio.run(gateway.call_tool("unknown", {}))
    with pytest.raises(ValueError, match="arguments"):
        asyncio.run(gateway.call_tool("lookup", {"unexpected": "x"}))


def test_rejects_mcp_error_malformed_tool_list_and_missing_url():
    async def broken_call(url, operation, name=None, arguments=None):
        if operation == "list_tools":
            return SimpleNamespace(tools=[{
                "name": "lookup", "description": "Look up a card",
                "inputSchema": {"type": "object", "properties": {}},
            }])
        return SimpleNamespace(isError=True, structuredContent=None, content=[])

    async def malformed_list(url, operation, name=None, arguments=None):
        return SimpleNamespace(tools=[{"name": "lookup", "inputSchema": {"type": "not-a-json-schema-type"}}])

    with pytest.raises(RuntimeError, match="MCP tool call failed"):
        asyncio.run(McpToolGateway(
            mcp_url="http://mcp:8001/mcp", operation_caller=broken_call,
        ).call_tool("lookup", {}))

    with pytest.raises(ValueError, match="tool schema"):
        asyncio.run(McpToolGateway(
            mcp_url="http://mcp:8001/mcp", operation_caller=malformed_list,
        ).list_tools())

    with pytest.raises(OperationalFailure) as error:
        asyncio.run(McpToolGateway(mcp_url="").list_tools())
    assert error.value.failure_code is FailureCode.CONFIGURATION_ERROR


def test_reuses_validated_tool_list_without_exposing_mutable_cache():
    calls = []
    schema = {"type": "object", "properties": {"term_id": {"type": "string"}},
              "required": ["term_id"], "additionalProperties": False}

    async def operation(url, action, name=None, arguments=None):
        calls.append(action)
        if action == "list_tools":
            return SimpleNamespace(tools=[{"name": "lookup", "inputSchema": schema}])
        return SimpleNamespace(isError=False, structuredContent={"status": "found"})

    async def case():
        gateway = McpToolGateway(mcp_url="http://mcp:8001/mcp", operation_caller=operation)
        first = await gateway.list_tools()
        first[0]["inputSchema"]["required"].clear()
        second = await gateway.list_tools()
        assert second[0]["inputSchema"]["required"] == ["term_id"]
        with pytest.raises(ValueError, match="arguments"):
            await gateway.call_tool("lookup", {})
        assert await gateway.call_tool("lookup", {"term_id": "pose_x"}) == {"status": "found"}
        assert calls == ["list_tools", "call_tool"]

    asyncio.run(case())


def test_expired_or_unknown_tool_refreshes_schema(monkeypatch):
    from backend.services import mcp_tool_gateway

    clock = [100.0]
    monkeypatch.setattr(mcp_tool_gateway, "monotonic", lambda: clock[0])
    calls = []

    async def operation(url, action, name=None, arguments=None):
        calls.append(action)
        if action == "list_tools":
            tool = "lookup" if len(calls) == 1 else "new_lookup"
            return SimpleNamespace(tools=[{"name": tool, "inputSchema": {
                "type": "object", "properties": {"term_id": {"type": "string"}},
                "required": ["term_id"], "additionalProperties": False,
            }}])
        return SimpleNamespace(isError=False, structuredContent={"status": "found"})

    async def case():
        gateway = McpToolGateway(mcp_url="http://mcp:8001/mcp", operation_caller=operation)
        assert (await gateway.list_tools())[0]["name"] == "lookup"
        clock[0] = 10900.0
        assert (await gateway.list_tools())[0]["name"] == "lookup"
        assert (await gateway.call_tool("new_lookup", {"term_id": "pose_x"}))["status"] == "found"
        assert calls == ["list_tools", "list_tools", "call_tool"]
        clock[0] = 25300.0
        assert (await gateway.list_tools())[0]["name"] == "new_lookup"
        assert calls.count("list_tools") == 3

    asyncio.run(case())


def test_concurrent_first_requests_share_one_tool_discovery():
    calls = 0
    started = asyncio.Event()
    release = asyncio.Event()

    async def operation(url, action, name=None, arguments=None):
        nonlocal calls
        calls += 1
        started.set()
        await release.wait()
        return SimpleNamespace(tools=[{"name": "lookup", "inputSchema": {"type": "object"}}])

    async def case():
        gateway = McpToolGateway(mcp_url="http://mcp:8001/mcp", operation_caller=operation)
        first = asyncio.create_task(gateway.list_tools())
        await started.wait()
        second = asyncio.create_task(gateway.list_tools())
        release.set()
        assert await asyncio.gather(first, second) == [[{
            "name": "lookup", "description": "", "inputSchema": {"type": "object"}
        }]] * 2
        assert calls == 1

    asyncio.run(case())


def test_failed_refresh_does_not_poison_tool_cache(monkeypatch):
    from backend.services import mcp_tool_gateway

    clock = [100.0]
    monkeypatch.setattr(mcp_tool_gateway, "monotonic", lambda: clock[0])
    calls = 0

    async def operation(url, action, name=None, arguments=None):
        nonlocal calls
        calls += 1
        if calls == 2:
            return SimpleNamespace(tools=[{"name": "lookup", "inputSchema": {
                "type": "invalid-schema-type"}}])
        return SimpleNamespace(tools=[{"name": "lookup", "inputSchema": {"type": "object"}}])

    async def case():
        gateway = McpToolGateway(mcp_url="http://mcp:8001/mcp", operation_caller=operation)
        await gateway.list_tools()
        clock[0] = 10900.0
        with pytest.raises(ValueError, match="tool schema"):
            await gateway.list_tools(refresh=True)
        assert (await gateway.list_tools())[0]["name"] == "lookup"
        assert calls == 2
        clock[0] = 14500.0
        assert (await gateway.list_tools())[0]["name"] == "lookup"
        assert calls == 3

    asyncio.run(case())
