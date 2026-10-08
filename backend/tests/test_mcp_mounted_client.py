"""배포 엔트리포인트의 MCP transport가 FastAPI lifespan에서 시작되는지 검증."""

import json

from fastapi.testclient import TestClient

from mcp_server.server import app
from mcp_server import server
from backend.services import searxng_pinterest_search


def _result(response) -> dict:
    assert response.status_code == 200
    data_lines = [line[5:].strip() for line in response.text.splitlines() if line.startswith("data:")]
    assert len(data_lines) == 1
    return json.loads(data_lines[0])["result"]


def test_mounted_mcp_client_lists_tool_and_calls_found_and_not_found(monkeypatch):
    requests = []

    async def search_json(url, params):
        requests.append((url, params))
        return {"results": [{"url": "https://kr.pinterest.com/pin/123/"}]}

    monkeypatch.setattr(server.settings, "searxng_base_url", "http://searxng:8080")
    monkeypatch.setattr(searxng_pinterest_search, "_load_search_json", search_json)
    headers = {"Accept": "application/json, text/event-stream"}
    with TestClient(app, base_url="http://127.0.0.1:8767") as client:
        initialized = client.post(
            "/mcp", headers=headers,
            json={
                "jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18", "capabilities": {},
                    "clientInfo": {"name": "contract-test", "version": "1"},
                },
            },
        )
        assert _result(initialized)["serverInfo"]["name"] == "illustration-reference-mcp"
        headers["Mcp-Session-Id"] = initialized.headers["Mcp-Session-Id"]
        headers["MCP-Protocol-Version"] = "2025-06-18"
        assert client.post(
            "/mcp", headers=headers,
            json={"jsonrpc": "2.0", "method": "notifications/initialized"},
        ).status_code == 202

        tools = _result(client.post(
            "/mcp", headers=headers,
            json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        ))
        assert "get_active_term_card" in [tool["name"] for tool in tools["tools"]]
        assert "search_pinterest_pins" in [tool["name"] for tool in tools["tools"]]

        for request_id, term_id, expected_status in (
            (3, "pose_contrapposto", "found"),
            (4, "missing_card_for_mcp_evidence", "not_found"),
        ):
            call = _result(client.post(
                "/mcp", headers=headers,
                json={
                    "jsonrpc": "2.0", "id": request_id, "method": "tools/call",
                    "params": {"name": "get_active_term_card", "arguments": {"term_id": term_id}},
                },
            ))
            assert call["isError"] is False
            payload = json.loads(call["content"][0]["text"])
            assert payload["status"] == expected_status
            if expected_status == "found":
                assert payload["term"]["term_id"] == term_id
            else:
                assert payload["reason_code"] == "TERM_NOT_ACTIVE"

        search = _result(client.post(
            "/mcp", headers=headers,
            json={
                "jsonrpc": "2.0", "id": 5, "method": "tools/call",
                "params": {"name": "search_pinterest_pins", "arguments": {
                    "role": "pose", "query_fragments": ["contrapposto pose", "standing reference"],
                }},
            },
        ))
        assert search["isError"] is False
        payload = json.loads(search["content"][0]["text"])
        assert payload["role"] == "pose"
        assert payload["pins"][0]["pin_url"] == "https://www.pinterest.com/pin/123/"
        assert len(payload["_search_trace"]) == 1
        assert payload["_search_trace"][0]["engine"] == "pinterest"
        assert payload["_search_trace"][0]["status"] == "success"
        assert requests[0][1]["q"] == (
            "!pin contrapposto pose standing reference drawing"
        )

        for request_id, fragments in (
            (6, ["unapproved phrase"]),
            (7, ["standing"]),  # fragment list does not identify an active card
        ):
            rejected = _result(client.post(
                "/mcp", headers=headers,
                json={
                    "jsonrpc": "2.0", "id": request_id, "method": "tools/call",
                    "params": {"name": "search_pinterest_pins", "arguments": {
                        "role": "pose", "query_fragments": fragments,
                    }},
                },
            ))
            assert rejected["isError"] is False
            assert json.loads(rejected["content"][0]["text"]) == {
                "failure_code": "INVALID_SEARCH_TERMS"
            }
        assert len(requests) == 1
