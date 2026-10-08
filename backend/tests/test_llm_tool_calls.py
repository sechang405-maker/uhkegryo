import asyncio
from types import SimpleNamespace

import httpx
import openai
import pytest

from backend.schemas.enums import FailureCode
from backend.services.llm import LLMInterpretationAdapter, LLMInvalidStructuredOutput, LLMTimeout
from backend.shared.config import Settings


class FakeCompletions:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.response


def adapter(message, *, error=None):
    completions = FakeCompletions(
        response=SimpleNamespace(choices=[SimpleNamespace(message=message)]), error=error,
    )
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    result = LLMInterpretationAdapter(
        client=client, settings=Settings(_env_file=None),
        system_message="system", user_template="{{request_text}}",
    )
    return result, completions


def test_sends_live_mcp_schemas_and_parses_model_tool_call():
    message = SimpleNamespace(tool_calls=[SimpleNamespace(
        id="call-1", function=SimpleNamespace(
            name="search_pinterest_pins",
            arguments='{"role":"pose","query_fragments":["standing pose"]}',
        ),
    )])
    llm, completions = adapter(message)
    tools = [{
        "name": "search_pinterest_pins", "description": "Search Pin links",
        "inputSchema": {"type": "object", "properties": {"role": {"type": "string"}}},
    }]

    calls = asyncio.run(llm.request_mcp_tool_calls(
        [{"role": "user", "content": "find a pose"}], tools, required=True,
    ))

    assert calls == [{
        "id": "call-1", "name": "search_pinterest_pins",
        "arguments": {"role": "pose", "query_fragments": ["standing pose"]},
    }]
    sent = completions.calls[0]
    assert sent["tool_choice"] == "required"
    assert sent["tools"] == [{
        "type": "function", "function": {
            "name": "search_pinterest_pins", "description": "Search Pin links",
            "parameters": tools[0]["inputSchema"],
        },
    }]
    assert "response_format" not in sent


def test_rejects_malformed_tool_arguments_and_allows_no_optional_call():
    bad, _ = adapter(SimpleNamespace(tool_calls=[SimpleNamespace(
        id="call-1", function=SimpleNamespace(name="lookup", arguments="not-json"),
    )]))
    with pytest.raises(LLMInvalidStructuredOutput) as error:
        asyncio.run(bad.request_mcp_tool_calls([], [{
            "name": "lookup", "inputSchema": {"type": "object"},
        }], required=True))
    assert error.value.failure_code is FailureCode.LLM_INVALID_STRUCTURED_OUTPUT

    optional, _ = adapter(SimpleNamespace(tool_calls=None))
    assert asyncio.run(optional.request_mcp_tool_calls([], [{
        "name": "lookup", "inputSchema": {"type": "object"},
    }], required=False)) == []


def test_maps_tool_call_request_timeout_to_existing_llm_error():
    timeout = openai.APITimeoutError(request=httpx.Request("POST", "https://openrouter.ai/api/v1"))
    llm, _ = adapter(None, error=timeout)

    with pytest.raises(LLMTimeout):
        asyncio.run(llm.request_mcp_tool_calls([], [{
            "name": "lookup", "inputSchema": {"type": "object"},
        }], required=True))



@pytest.mark.parametrize(("call_id", "name"), [
    (None, "lookup"), ("", "lookup"), (1, "lookup"), ("call-1", None),
    ("call-1", ""), ("call-1", 1),
])
def test_rejects_tool_calls_without_nonempty_string_id_and_name(call_id, name):
    call = SimpleNamespace(id=call_id, function=SimpleNamespace(name=name, arguments="{}"))
    bad, _ = adapter(SimpleNamespace(tool_calls=[call]))
    with pytest.raises(LLMInvalidStructuredOutput) as error:
        asyncio.run(bad.request_mcp_tool_calls([], [{"name": "lookup", "inputSchema": {"type": "object"}}], required=True))
    assert error.value.failure_code is FailureCode.LLM_INVALID_STRUCTURED_OUTPUT
