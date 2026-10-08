"""독립 MCP client로 tool 목록과 활성/미등록 TERM_CARD 결과를 검증한다."""

import argparse
import asyncio
import json
import os

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


TOOL_NAME = "get_active_term_card"


async def check_anonymous_denied(url: str) -> int:
    request = {
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {}, "clientInfo": {"name": "access-check", "version": "1"},
        },
    }
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.post(
            url, json=request,
            headers={"Accept": "application/json, text/event-stream"},
        )
    if response.status_code not in (401, 403):
        raise AssertionError(f"Anonymous access was not denied: HTTP {response.status_code}")
    return response.status_code


def _payload(result) -> dict:
    if result.isError:
        raise RuntimeError("MCP tool returned an error")
    if result.structuredContent:
        data = result.structuredContent
    else:
        if len(result.content) != 1 or result.content[0].type != "text":
            raise ValueError("Expected one JSON text result")
        data = json.loads(result.content[0].text)
    if not isinstance(data, dict):
        raise ValueError("Expected a JSON object")
    return data


async def verify(url: str, found_id: str, missing_id: str, token: str) -> dict:
    headers = {"Authorization": f"Bearer {token}"} if token else None
    async with streamablehttp_client(url, headers=headers) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            names = sorted(tool.name for tool in (await session.list_tools()).tools)
            if TOOL_NAME not in names:
                raise AssertionError(f"Missing tool: {TOOL_NAME}")

            found = _payload(await session.call_tool(TOOL_NAME, {"term_id": found_id}))
            term = found.get("term")
            if (
                found.get("status") != "found"
                or not found.get("catalog_version")
                or not isinstance(term, dict)
                or term.get("term_id") != found_id
                or not all(key in term for key in (
                    "role", "label_ko", "label_en", "query_fragments", "look_for"
                ))
            ):
                raise AssertionError("Active card response violates MCP contract")

            missing = _payload(await session.call_tool(TOOL_NAME, {"term_id": missing_id}))
            if missing != {"status": "not_found", "reason_code": "TERM_NOT_ACTIVE"}:
                raise AssertionError("Unknown card response violates MCP contract")

            return {
                "tools": names,
                "found": {
                    "status": found["status"],
                    "catalog_version": found["catalog_version"],
                    "term_id": term["term_id"],
                    "role": term["role"],
                },
                "not_found": missing,
            }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8765/mcp")
    parser.add_argument("--found-id", default="pose_contrapposto")
    parser.add_argument("--missing-id", default="missing_card_for_mcp_evidence")
    parser.add_argument("--check-denied", action="store_true", help="먼저 무인증 요청이 401/403인지 확인")
    args = parser.parse_args()
    token = os.getenv("MCP_ID_TOKEN", "")
    if args.check_denied and not token:
        parser.error("--check-denied requires MCP_ID_TOKEN for the authorized call")
    denied_status = asyncio.run(check_anonymous_denied(args.url)) if args.check_denied else None
    evidence = asyncio.run(verify(
        args.url, args.found_id, args.missing_id, token
    ))
    if denied_status is not None:
        evidence["anonymous_http_status"] = denied_status
    print(json.dumps(evidence, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
