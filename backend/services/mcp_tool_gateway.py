"""Discover and execute tools registered on the configured MCP server."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from copy import deepcopy
import os
from time import monotonic
from typing import Any
from urllib.parse import urlsplit

import httpx
from jsonschema import SchemaError, ValidationError, validate
from jsonschema.validators import validator_for

from backend.schemas.enums import FailureCode
from backend.services.failure_mapping import OperationalFailure

TOOL_CACHE_TTL_SECONDS = 4 * 60 * 60


class McpToolGateway:
    def __init__(self, *, mcp_url: str, operation_caller=None) -> None:
        self._mcp_url = mcp_url
        self._operation_caller = operation_caller or _call_mcp_operation
        self._tools: dict[str, dict] = {}
        self._cache_expires_at = 0.0
        self._list_lock = asyncio.Lock()

    async def list_tools(self, *, refresh: bool = False) -> list[dict]:
        if not self._mcp_url:
            raise OperationalFailure(FailureCode.CONFIGURATION_ERROR)
        if not refresh and monotonic() < self._cache_expires_at:
            return deepcopy(list(self._tools.values()))
        async with self._list_lock:
            if not refresh and monotonic() < self._cache_expires_at:
                return deepcopy(list(self._tools.values()))
            result = await self._operation_caller(self._mcp_url, "list_tools")
            raw_tools = getattr(result, "tools", None)
            if not isinstance(raw_tools, list):
                raise ValueError("MCP tool list is malformed")

            tools = []
            for raw_tool in raw_tools:
                item = _to_mapping(raw_tool)
                name = item.get("name")
                description = item.get("description")
                input_schema = item.get("inputSchema", item.get("input_schema"))
                if not isinstance(name, str) or not name or not isinstance(input_schema, Mapping):
                    raise ValueError("MCP tool schema is malformed")
                try:
                    validator_for(input_schema).check_schema(input_schema)
                except SchemaError as error:
                    raise ValueError("MCP tool schema is malformed") from error
                if description is not None and not isinstance(description, str):
                    raise ValueError("MCP tool schema is malformed")
                tools.append({
                    "name": name, "description": description or "",
                    "inputSchema": deepcopy(dict(input_schema)),
                })
            self._tools = {tool["name"]: tool for tool in tools}
            self._cache_expires_at = monotonic() + TOOL_CACHE_TTL_SECONDS
            return deepcopy(tools)

    async def call_tool(self, name: str, arguments: dict) -> dict:
        await self.list_tools()
        tool = self._tools.get(name)
        if tool is None:
            await self.list_tools(refresh=True)
            tool = self._tools.get(name)
            if tool is None:
                raise ValueError(f"MCP tool is not listed: {name}")
        if not isinstance(arguments, dict):
            raise ValueError("MCP tool arguments must be an object")
        try:
            validate(instance=arguments, schema=tool["inputSchema"])
        except ValidationError as error:
            raise ValueError("MCP tool arguments do not match inputSchema") from error

        result = await self._operation_caller(
            self._mcp_url, "call_tool", name=name, arguments=arguments
        )
        if getattr(result, "isError", False):
            raise RuntimeError(f"MCP tool call failed: {name}")
        structured = getattr(result, "structuredContent", None)
        if isinstance(structured, Mapping):
            return dict(structured)

        content = getattr(result, "content", None)
        if not isinstance(content, list):
            raise ValueError("MCP tool result is malformed")
        return {"content": [_to_mapping(block) for block in content]}


def _to_mapping(value: Any) -> dict:
    if isinstance(value, Mapping):
        return dict(value)
    if hasattr(value, "model_dump"):
        return value.model_dump(by_alias=True, mode="json")
    raise ValueError("MCP result item is malformed")


async def _call_mcp_operation(
    url: str, operation: str, *, name: str | None = None, arguments: dict | None = None
) -> Any:
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    headers = await _auth_headers(url)
    async with streamablehttp_client(url, headers=headers) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            if operation == "list_tools":
                return await session.list_tools()
            if operation == "call_tool" and name is not None and arguments is not None:
                return await session.call_tool(name, arguments)
    raise ValueError(f"Unsupported MCP operation: {operation}")


async def _auth_headers(url: str) -> dict[str, str] | None:
    token = os.getenv("MCP_ID_TOKEN", "")
    parsed = urlsplit(url)
    if not token and parsed.scheme == "https":
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(
                "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/identity",
                params={"audience": f"{parsed.scheme}://{parsed.netloc}", "format": "full"},
                headers={"Metadata-Flavor": "Google"},
            )
            response.raise_for_status()
            token = response.text
    return {"Authorization": f"Bearer {token}"} if token else None
