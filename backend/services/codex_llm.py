"""Reuse the interpreter/recall contracts with the local Codex CLI transport."""
import asyncio
import json
from types import SimpleNamespace

from backend.services import codex_runtime
from backend.services.llm import LLMInterpretationAdapter, LLMConfigurationError, LLMTimeout


def strict_schema(schema):
    schema = json.loads(json.dumps(schema))
    def visit(node):
        if isinstance(node, dict):
            node.pop('default', None)
            if node.get('type') == 'object':
                node['required'] = list(node.get('properties', {}))
                node['additionalProperties'] = False
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for value in node:
                visit(value)
    visit(schema)
    return schema


class CodexInterpretationAdapter(LLMInterpretationAdapter):
    image_search_enabled = False

    def __init__(self, **kwargs):
        # A non-null sentinel prevents construction of an OpenRouter/API-key client.
        super().__init__(client=object(), **kwargs)
        self._slot = asyncio.Semaphore(1)
        self._generate = codex_runtime.generate

    def _memory_output_format(self, output_type):
        return {'json_schema': {'schema': strict_schema(output_type.model_json_schema())}}

    async def _request(self, messages, *, output_format=None, tools=None, tool_choice=None, json_mode=True):
        if tools is not None or not output_format:
            raise LLMConfigurationError('Local Codex requires a response schema; live search tools are disabled')
        try:
            async with asyncio.timeout(self.settings.codex_timeout_seconds):
                async with self._slot:
                    content = await self._generate(self.settings, messages, output_format['json_schema']['schema'])
        except TimeoutError:
            raise LLMTimeout('Codex request timed out') from None
        return SimpleNamespace(choices=[SimpleNamespace(finish_reason='stop',
            message=SimpleNamespace(content=content))], usage=None)
