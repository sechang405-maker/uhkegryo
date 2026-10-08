"""T14 기본 해석 LLM 어댑터 테스트.

진짜 API 호출 없이 가짜 transport로 오류 분류 전 경로와 prompt 조립·출력 검증 계약을 확인한다.
"""
import asyncio
import contextlib
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import httpx
import openai
import pytest

from backend.schemas.enums import FailureCode, InterpretationState
from backend.services import llm
from backend.schemas.models import InterpretationOutput
from backend.shared.config import Settings, get_settings

PROMPT_ENV_VAR = "INTERPRETER_PROMPT_PATH"
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
REPO_PROMPT_FILE = REPO_ROOT / "prompts" / "uhkegryo-interpreter-v0.md"


def _real_settings() -> Settings:
    """저장소 `.env`와 무관하게 실제 Settings를 로드한다 (설정 로딩 자체를 검증)."""
    return Settings(_env_file=None)


def _write_prompt(path: Path, marker: str) -> Path:
    path.write_text(
        f"## System message\n```text\n{marker}\n```\n\n"
        "## User message template\n```text\n"
        "{{request_text}}\n{{active_cards_json}}\n```\n",
        encoding="utf-8",
    )
    return path

SELECT_JSON = """{
  "interpretation_state": "select_terms",
  "clarification_type": null,
  "selections": [
    {"role": "pose", "term_id": "pose_contrapposto", "evidence": ["반동", "허리 꼬임"], "confidence": 0.9}
  ],
  "unresolved_constraints": [],
  "clarifying_question": null
}"""

CLARIFY_JSON = """{
  "interpretation_state": "needs_clarification",
  "clarification_type": "insufficient_visual_evidence",
  "selections": [],
  "unresolved_constraints": ["체형 비율을 확정할 실제 신체 단서가 없음"],
  "clarifying_question": "의상을 제외한 실제 체형 비율을 찾으시나요?"
}"""

SYSTEM_EXAMPLE = "You are the structured interpreter for UH Keguryeo."
TEMPLATE_EXAMPLE = (
    "사용자 요청:\n<request_text>\n{{request_text}}\n</request_text>\n"
    "활성 TERM_CARD JSON:\n<active_cards_json>\n{{active_cards_json}}\n</active_cards_json>"
)


class _FakeUsage:
    def __init__(self, prompt_tokens=10, completion_tokens=5, total_tokens=15):
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.total_tokens = total_tokens


class _FakeMessage:
    def __init__(self, content):
        self.content = content
        self.role = "assistant"


class _FakeChoice:
    def __init__(self, content):
        self.message = _FakeMessage(content)


class _FakeResponse:
    def __init__(self, content):
        self.choices = [_FakeChoice(content)]
        self.usage = _FakeUsage()


class _FakeCompletions:
    def __init__(self, responses=None, error=None):
        self._responses = list(responses or [])
        self._error = error
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if self._error is not None:
            raise self._error
        if not self._responses:
            raise AssertionError("가짜 응답이 없습니다")
        return self._responses.pop(0)


class _FakeChat:
    def __init__(self, completions):
        self.completions = completions


class _FakeClient:
    def __init__(self, completions):
        self.chat = _FakeChat(completions)


def _adapter(completions, **kwargs):
    return llm.LLMInterpretationAdapter(
        client=_FakeClient(completions),
        system_message=SYSTEM_EXAMPLE,
        user_template=TEMPLATE_EXAMPLE,
        **kwargs,
    )


def _run(coro):
    return asyncio.run(coro)


# --- prompt 조립 -------------------------------------------------------------


def test_load_interpreter_prompt_reads_repo_file():
    system_message, template = llm.load_interpreter_prompt(REPO_PROMPT_FILE)
    assert "You are the structured interpreter for UH Keguryeo." in system_message
    assert "{{request_text}}" in template
    assert "{{active_cards_json}}" in template
    assert "```" not in system_message
    assert "```" not in template


@pytest.mark.parametrize(
    "prompt_text",
    [
        "## User message template\n```text\n{{request_text}}\n```\n",
        "## System message\n```text\nsystem\n```\n",
    ],
    ids=["system-heading-missing", "user-template-heading-missing"],
)
def test_load_interpreter_prompt_rejects_missing_sections(tmp_path, prompt_text):
    prompt_path = tmp_path / "malformed-prompt.md"
    prompt_path.write_text(prompt_text, encoding="utf-8")

    with pytest.raises(llm.PromptConfigurationError) as exc:
        llm.load_interpreter_prompt(prompt_path)

    assert exc.value.failure_code is FailureCode.CONFIGURATION_ERROR
    assert exc.value.retryable is False


@pytest.mark.parametrize(
    "prompt_text",
    [
        "## System message\n```text\nsystem\n\n"
        "## User message template\n```text\n{{request_text}}\n```\n",
        "## System message\n```text\nsystem\n```\n\n"
        "## User message template\n```text\n{{request_text}}\n",
    ],
    ids=["system-fence-unclosed", "user-template-fence-unclosed"],
)
def test_load_interpreter_prompt_rejects_unclosed_fences(tmp_path, prompt_text):
    prompt_path = tmp_path / "malformed-prompt.md"
    prompt_path.write_text(prompt_text, encoding="utf-8")

    with pytest.raises(llm.PromptConfigurationError) as exc:
        llm.load_interpreter_prompt(prompt_path)

    assert exc.value.failure_code is FailureCode.CONFIGURATION_ERROR
    assert exc.value.retryable is False


def test_render_user_message_replaces_placeholders():
    rendered = llm.render_user_message(TEMPLATE_EXAMPLE, "반동 자세", "[{...}]")
    assert "반동 자세" in rendered
    assert "[{...}]" in rendered
    assert "{{request_text}}" not in rendered
    assert "{{active_cards_json}}" not in rendered


def test_format_active_cards_json_keeps_only_contract_fields(snapshot_factory, card_factory):
    card = card_factory("pose_contrapposto", role="pose")
    snapshot = snapshot_factory([card])
    payload = llm.format_active_cards_json(snapshot)
    parsed = json.loads(payload)
    item = parsed["active_cards"][0]
    assert item["term_id"] == "pose_contrapposto"
    assert item["role"] == "pose"
    assert item["label_ko"] == "라벨"
    assert "confidence_gate" in item
    assert "requires_all_of" in item
    assert "requires_any_of" in item
    assert "query_fragments" not in item
    assert "look_for" not in item
    assert "source_answer_draft" not in item
    assert item["plain_meaning_ko"] == "초안 설명"
    assert item["reference_checkpoints_ko"] == ["라벨 관찰 지점"]
    snapshot.feedback["pose_contrapposto"] = {"plain_meaning_ko": "검수된 의미", "reference_checkpoints_ko": ["검수 지점"]}
    updated = json.loads(llm.format_active_cards_json(snapshot))["active_cards"][0]
    assert updated["plain_meaning_ko"] == "검수된 의미"
    assert updated["reference_checkpoints_ko"] == ["검수 지점"]


# --- 정상 출력 ---------------------------------------------------------------


def test_interpret_select_terms_valid():
    completions = _FakeCompletions(responses=[_FakeResponse(SELECT_JSON)])
    adapter = _adapter(completions)
    result = _run(adapter.interpret("반동 자세를 찾아요", job_id="r1", session_id="session-1", attempt=1, max_attempts=3, active_cards_json="{}"))
    assert isinstance(result, InterpretationOutput)
    assert result.interpretation_state is InterpretationState.SELECT_TERMS
    assert len(result.selections) == 1
    assert result.selections[0].term_id == "pose_contrapposto"
    assert result.selections[0].evidence == ["반동", "허리 꼬임"]


def test_interpret_needs_clarification_valid():
    completions = _FakeCompletions(responses=[_FakeResponse(CLARIFY_JSON)])
    adapter = _adapter(completions)
    result = _run(adapter.interpret("자연스러운 자세", job_id="r1", session_id="session-1", attempt=1, max_attempts=3))
    assert result.interpretation_state is InterpretationState.NEEDS_CLARIFICATION
    assert result.clarifying_question
    assert result.clarification_type is not None


def test_interpret_passes_system_and_user_messages():
    completions = _FakeCompletions(responses=[_FakeResponse(SELECT_JSON)])
    adapter = _adapter(completions)
    _run(adapter.interpret("반동", job_id="r1", session_id="session-1", attempt=1, max_attempts=3, active_cards_json='{"active_cards": []}'))
    assert len(completions.calls) == 1
    call = completions.calls[0]
    assert call["model"] == "openai/gpt-4o-mini"
    assert call["response_format"] == {"type": "json_object"}
    assert "extra_body" not in call
    messages = call["messages"]
    assert messages[0]["role"] == "system"
    assert messages[0]["content"].startswith(SYSTEM_EXAMPLE + "\n")
    assert "Include answer_text" in messages[0]["content"]
    assert messages[1]["role"] == "user"
    assert "반동" in messages[1]["content"]
    assert '{"active_cards": []}' in messages[1]["content"]


def test_interpret_sends_beginner_friendly_answer_rules_to_model():
    completions = _FakeCompletions(responses=[_FakeResponse(SELECT_JSON)])
    adapter = _adapter(completions)
    _run(adapter.interpret("반동", job_id="r1", session_id="session-1", attempt=1, max_attempts=3))
    system = completions.calls[0]["messages"][0]["content"]
    assert "Do not expose internal term IDs" in system
    assert "plain meanings and reference observation points" in system
    assert "Avoid repetitive selection reports" in system
    assert "Write answer_text in Korean Markdown" in system
    assert "Do not wrap the whole answer in a code fence" in system
    assert "Do not include raw HTML, images, links, tables or code blocks" in system
    assert "Use only the supplied catalog and supported evidence" in system
    assert "For needs_clarification use an empty string" in system


def test_interpretation_validation_feedback_is_never_added_as_system_message():
    completions = _FakeCompletions(responses=[_FakeResponse(SELECT_JSON)])
    _run(_adapter(completions).interpret(
        "반동", job_id="r1", session_id="session-1", attempt=1, max_attempts=3,
    ))
    messages = completions.calls[0]["messages"]
    assert [message["role"] for message in messages] == ["system", "user"]


# --- 관측 계약 (observability-and-prompt-versioning.md) ----------------------

_REQUEST_TEXT = "한쪽 다리에 힘 주고 상체가 살짝 틀어진 마른 캐릭터"


def _langfuse_generation_kwargs(monkeypatch, *, with_keys=True):
    """가짜 langfuse 모듈로 trace 전송 내용을 캡처한다. 네트워크는 호출하지 않는다."""
    recorded = {}

    class _FakeGeneration:
        def update(self, **kwargs):
            recorded.setdefault("generation_update", {}).update(kwargs)
            recorded["generation"].update({k: v for k, v in kwargs.items()
                                          if k in ("input", "metadata")})

    class _FakeLangfuse:
        def __init__(self, **kwargs):
            recorded["init"] = kwargs

        def get_current_trace_id(self):
            return "worker-owned-trace"

        def start_as_current_observation(self, **kwargs):
            recorded["parent_trace_id"] = self.get_current_trace_id()
            recorded["generation"] = kwargs
            return contextlib.nullcontext(_FakeGeneration())

    fake_module = type(sys)("langfuse")
    fake_module.Langfuse = _FakeLangfuse
    monkeypatch.setitem(sys.modules, "langfuse", fake_module)

    settings = _real_settings()
    if with_keys:
        monkeypatch.setattr(settings, "langfuse_public_key", "pk-test", raising=False)
        monkeypatch.setattr(settings, "langfuse_secret_key", "sk-test", raising=False)
    else:
        monkeypatch.setattr(settings, "langfuse_public_key", "", raising=False)
        monkeypatch.setattr(settings, "langfuse_secret_key", "", raising=False)

    completions = _FakeCompletions(responses=[_FakeResponse(SELECT_JSON)])
    adapter = _adapter(completions, settings=settings)
    _run(adapter.interpret(_REQUEST_TEXT, job_id="job-42", session_id="session-42", attempt=2, max_attempts=3, active_cards_json="{}"))
    return recorded, adapter


def test_interpret_structured_log_carries_job_id(caplog):
    """구조화 로그가 관측 스펙이 요구하는 `job_id`와 `prompt_version`을 남긴다."""
    completions = _FakeCompletions(responses=[_FakeResponse(SELECT_JSON)])
    adapter = _adapter(completions)
    with caplog.at_level("INFO", logger="backend.services.llm"):
        _run(adapter.interpret(_REQUEST_TEXT, job_id="job-42", session_id="session-1", attempt=1, max_attempts=3, active_cards_json="{}"))

    payloads = [json.loads(r.message) for r in caplog.records if r.name == "backend.services.llm"]
    ok = [p for p in payloads if p.get("event") == "llm.interpret.ok"]
    assert len(ok) == 1
    assert ok[0]["job_id"] == "job-42"
    assert ok[0]["prompt_version"] == adapter.prompt_version


def test_structured_log_does_not_carry_request_text(caplog):
    """원문은 Langfuse trace에만 남긴다. 일반 애플리케이션 로그에는 남기지 않는다."""
    completions = _FakeCompletions(responses=[_FakeResponse(SELECT_JSON)])
    adapter = _adapter(completions)
    with caplog.at_level("DEBUG", logger="backend.services.llm"):
        _run(adapter.interpret(_REQUEST_TEXT, job_id="job-42", session_id="session-1", attempt=1, max_attempts=3, active_cards_json="{}"))

    messages = [r.getMessage() for r in caplog.records if r.name == "backend.services.llm"]
    assert messages
    assert all(_REQUEST_TEXT not in message for message in messages)
    assert all("session-1" not in message for message in messages)


def test_langfuse_input_carries_request_text(monkeypatch):
    """Langfuse trace input에 사용자 요청 원문이 전달된다."""
    recorded, _ = _langfuse_generation_kwargs(monkeypatch)
    assert recorded["generation"]["input"] == {"request_text": _REQUEST_TEXT}


def test_langfuse_metadata_keeps_job_id(monkeypatch):
    """job 관측 context가 원문 없이 worker trace 아래 observation에 기록된다."""
    recorded, _ = _langfuse_generation_kwargs(monkeypatch)
    metadata = recorded["generation"]["metadata"]
    assert metadata["job_id"] == "job-42"
    assert metadata["session_id"] == "session-42"
    assert metadata["attempt"] == 2
    assert metadata["max_attempts"] == 3
    assert recorded["generation"]["model"] == "openai/gpt-4o-mini"
    assert recorded["generation"]["version"] == "uhkegryo-interpreter-v0"
    assert recorded["parent_trace_id"] == "worker-owned-trace"
    assert recorded["generation_update"]["usage_details"] == {
        "input_tokens": 10, "output_tokens": 5, "total_tokens": 15
    }


def test_langfuse_keeps_prompt_version(monkeypatch):
    """generation 이름은 프롬프트 버전과 독립적으로 해석 종류를 표시한다."""
    recorded, adapter = _langfuse_generation_kwargs(monkeypatch)
    assert recorded["generation"]["name"] == "interpreter"
    assert recorded["generation"]["version"] == adapter.prompt_version


@pytest.mark.parametrize(("method_name", "arguments", "expected"), [
    ("interpret", {}, "interpreter"),
    ("memory", {"operation": "classify"}, "memory-classify"),
    ("memory", {"operation": "answer"}, "memory-answer"),
    ("request_mcp_tool_calls", {}, "mcp-tool-selection"),
])
def test_generation_name_identifies_call_kind(method_name, arguments, expected):
    from backend.services.llm import _generation_name

    assert _generation_name(method_name, arguments) == expected


def test_langfuse_disabled_sends_nothing(monkeypatch):
    """키가 없으면 네트워크 호출 없이 조용히 종료한다."""
    recorded, _ = _langfuse_generation_kwargs(monkeypatch, with_keys=False)
    assert recorded == {}


@pytest.mark.parametrize("missing", ["job_id", "session_id", "attempt", "max_attempts"])
def test_interpret_requires_worker_context_keywords(missing):
    """worker trace context는 adapter 계약에서 모두 필수다."""
    completions = _FakeCompletions(responses=[_FakeResponse(SELECT_JSON)])
    adapter = _adapter(completions)
    context = {
        "job_id": "job-42",
        "session_id": "session-42",
        "attempt": 1,
        "max_attempts": 3,
    }
    context.pop(missing)
    with pytest.raises(TypeError):
        adapter.interpret("반동", **context)


def test_langfuse_does_not_create_root_trace_without_worker_context(monkeypatch):
    recorded = {}

    class _FakeLangfuse:
        def __init__(self, **kwargs):
            pass

        def get_current_trace_id(self):
            return None

        def start_as_current_observation(self, **kwargs):
            recorded["generation"] = kwargs
            raise AssertionError("adapter must not create a root observation")

    fake_module = type(sys)("langfuse")
    fake_module.Langfuse = _FakeLangfuse
    monkeypatch.setitem(sys.modules, "langfuse", fake_module)
    settings = _real_settings()
    settings.langfuse_public_key = "pk-test"
    settings.langfuse_secret_key = "sk-test"
    adapter = _adapter(_FakeCompletions(responses=[_FakeResponse(SELECT_JSON)]), settings=settings)

    _run(adapter.interpret(
        _REQUEST_TEXT, job_id="job-42", session_id="session-42", attempt=1, max_attempts=3
    ))
    assert "generation" not in recorded


# --- 구조화 출력 실패 (LLM_INVALID_STRUCTURED_OUTPUT) ------------------------


def test_interpret_invalid_json_raises_structured_output_error():
    completions = _FakeCompletions(responses=[_FakeResponse("이건 JSON이 아닙니다")])
    adapter = _adapter(completions)
    with pytest.raises(llm.LLMInvalidStructuredOutput):
        _run(adapter.interpret("반동", job_id="r1", session_id="session-1", attempt=1, max_attempts=3))


def test_interpret_schema_violation_raises_structured_output_error():
    bad = '{"interpretation_state": "select_terms", "selections": [], "clarifying_question": null}'
    completions = _FakeCompletions(responses=[_FakeResponse(bad)])
    adapter = _adapter(completions)
    with pytest.raises(llm.LLMInvalidStructuredOutput) as exc:
        _run(adapter.interpret("반동", job_id="r1", session_id="session-1", attempt=1, max_attempts=3))
    assert exc.value.error_type == "pydantic_validation_error"


def test_interpret_empty_content_is_incomplete_upstream_response():
    completions = _FakeCompletions(responses=[_FakeResponse("")])
    adapter = _adapter(completions)
    with pytest.raises(llm.LLMIncompleteResponse) as exc:
        _run(adapter.interpret("반동", job_id="r1", session_id="session-1", attempt=1, max_attempts=3))
    assert exc.value.error_type == "incomplete_or_unclassified_upstream"


def test_interpret_empty_choices_are_incomplete_upstream_response():
    response = _FakeResponse(SELECT_JSON)
    response.choices = []
    adapter = _adapter(_FakeCompletions(responses=[response]))
    with pytest.raises(llm.LLMIncompleteResponse) as exc:
        _run(adapter.interpret("반동", job_id="r1", session_id="s1", attempt=1, max_attempts=3))
    assert exc.value.error_type == "incomplete_or_unclassified_upstream"


def test_interpret_unfinished_choice_is_incomplete_upstream_response():
    response = _FakeResponse(SELECT_JSON)
    response.choices[0].finish_reason = "length"
    adapter = _adapter(_FakeCompletions(responses=[response]))
    with pytest.raises(llm.LLMIncompleteResponse) as exc:
        _run(adapter.interpret("반동", job_id="r1", session_id="s1", attempt=1, max_attempts=3))
    assert exc.value.error_type == "incomplete_or_unclassified_upstream"


# --- 오류 분류 (LLM_* retryable) ---------------------------------------------


_REQ = httpx.Request("POST", "https://openrouter.ai/api/v1")


def test_interpret_timeout_raises_llm_timeout():
    error = openai.APITimeoutError(request=_REQ)
    completions = _FakeCompletions(error=error)
    adapter = _adapter(completions)
    with pytest.raises(llm.LLMTimeout) as exc:
        _run(adapter.interpret("반동", job_id="r1", session_id="session-1", attempt=1, max_attempts=3))
    assert exc.value.failure_code is FailureCode.LLM_TIMEOUT
    assert exc.value.error_type == "timeout"
    assert exc.value.retryable


def test_interpret_rate_limited_raises_llm_rate_limited():
    error = openai.RateLimitError(
        "rate", response=httpx.Response(status_code=429, request=_REQ), body=None
    )
    completions = _FakeCompletions(error=error)
    adapter = _adapter(completions)
    with pytest.raises(llm.LLMRateLimited) as exc:
        _run(adapter.interpret("반동", job_id="r1", session_id="session-1", attempt=1, max_attempts=3))
    assert exc.value.failure_code is FailureCode.LLM_RATE_LIMITED
    assert exc.value.error_type == "rate_limited"
    assert exc.value.retryable


@pytest.mark.parametrize("header, expected", [("60", 30000), ("0.5", 1000), ("bad", None)])
def test_rate_limit_retry_after_is_clamped_for_worker(header, expected):
    error = openai.RateLimitError(
        "rate",
        response=httpx.Response(status_code=429, headers={"Retry-After": header}, request=_REQ),
        body=None,
    )
    adapter = _adapter(_FakeCompletions(error=error))
    with pytest.raises(llm.LLMRateLimited) as exc:
        _run(adapter.interpret("반동", job_id="r1", session_id="s1", attempt=1, max_attempts=3))
    assert exc.value.retry_after_ms == expected


def test_retry_after_http_date_is_converted_to_milliseconds():
    now = datetime(2026, 9, 28, 0, 0, 0, tzinfo=timezone.utc)
    header = format_datetime(now + timedelta(seconds=12), usegmt=True)
    error = openai.RateLimitError(
        "rate",
        response=httpx.Response(status_code=429, headers={"Retry-After": header}, request=_REQ),
        body=None,
    )
    assert llm._retry_after_ms(error, now=now) == 12000


def test_expired_retry_after_http_date_falls_back_to_worker_backoff():
    now = datetime(2026, 9, 28, 0, 0, 0, tzinfo=timezone.utc)
    header = format_datetime(now - timedelta(seconds=1), usegmt=True)
    error = openai.RateLimitError(
        "rate",
        response=httpx.Response(status_code=429, headers={"Retry-After": header}, request=_REQ),
        body=None,
    )
    assert llm._retry_after_ms(error, now=now) is None


def test_interpret_upstream_5xx_raises_llm_upstream_unavailable():
    error = openai.InternalServerError(
        "up", response=httpx.Response(status_code=500, request=_REQ), body=None
    )
    completions = _FakeCompletions(error=error)
    adapter = _adapter(completions)
    with pytest.raises(llm.LLMUpstreamUnavailable) as exc:
        _run(adapter.interpret("반동", job_id="r1", session_id="session-1", attempt=1, max_attempts=3))
    assert exc.value.failure_code is FailureCode.LLM_UPSTREAM_UNAVAILABLE
    assert exc.value.error_type == "upstream_5xx"
    assert exc.value.retryable


@pytest.mark.parametrize("status", [401, 403])
def test_provider_authentication_error_is_configuration_failure(status):
    error = openai.APIStatusError(
        "private API key", response=httpx.Response(status, request=_REQ), body=None
    )
    adapter = _adapter(_FakeCompletions(error=error))
    with pytest.raises(llm.LLMConfigurationError) as caught:
        _run(adapter.interpret("자세", job_id="job", session_id="session", attempt=1, max_attempts=3))
    assert caught.value.failure_code is FailureCode.CONFIGURATION_ERROR
    assert not caught.value.retryable
    assert "private API key" not in str(caught.value)


def test_interpret_connection_error_raises_llm_upstream_unavailable():
    error = openai.APIConnectionError(request=_REQ)
    completions = _FakeCompletions(error=error)
    adapter = _adapter(completions)
    with pytest.raises(llm.LLMUpstreamUnavailable) as exc:
        _run(adapter.interpret("반동", job_id="r1", session_id="session-1", attempt=1, max_attempts=3))
    assert exc.value.error_type == "incomplete_or_unclassified_upstream"


@pytest.mark.parametrize(
    "cls",
    [llm.LLMTimeout, llm.LLMRateLimited, llm.LLMUpstreamUnavailable, llm.LLMInvalidStructuredOutput],
)
def test_llm_errors_are_retryable(cls):
    assert cls.retryable is True


# --- 리뷰 반영: INTERPRETER_PROMPT_PATH는 env → 실제 Settings → 어댑터 경로까지 ----
# 폴백 없음. 미설정·경로 없음·읽기 불가면 모두 PromptConfigurationError로 실패해야 한다.


def test_settings_reads_interpreter_prompt_path_from_env(tmp_path):
    prompt_file = _write_prompt(tmp_path / "env-prompt.md", "ENV SYSTEM MARKER")
    with patch.dict(os.environ, {PROMPT_ENV_VAR: str(prompt_file)}):
        settings = _real_settings()
    assert settings.interpreter_prompt_path == str(prompt_file)


def test_settings_interpreter_prompt_path_defaults_to_empty():
    with patch.dict(os.environ, {PROMPT_ENV_VAR: ""}):
        settings = _real_settings()
    assert settings.interpreter_prompt_path == ""


def test_default_prompt_path_uses_env_var_via_real_settings(tmp_path):
    prompt_file = _write_prompt(tmp_path / "my-prompt.md", "Hi")
    with patch.dict(os.environ, {PROMPT_ENV_VAR: str(prompt_file)}):
        settings = _real_settings()
        p = llm.default_prompt_path(settings)
        system_message, template = llm.load_interpreter_prompt(p)
    assert p == prompt_file
    assert "Hi" in system_message
    assert "{{request_text}}" in template


def test_default_prompt_path_without_arg_still_reads_env_var(tmp_path):
    """인자를 넘기지 않아도 get_settings()가 env var를 실제로 읽는지 확인."""
    prompt_file = _write_prompt(tmp_path / "no-arg-prompt.md", "NO ARG MARKER")
    with patch.dict(os.environ, {PROMPT_ENV_VAR: str(prompt_file)}):
        get_settings.cache_clear()
        try:
            p = llm.default_prompt_path()
        finally:
            get_settings.cache_clear()
    assert p == prompt_file


def test_default_prompt_path_raises_when_env_not_configured():
    with patch.dict(os.environ, {PROMPT_ENV_VAR: ""}):
        settings = _real_settings()
        with pytest.raises(llm.PromptConfigurationError) as exc:
            llm.default_prompt_path(settings)
    assert PROMPT_ENV_VAR in str(exc.value)


def test_default_prompt_path_raises_when_configured_file_missing():
    with patch.dict(os.environ, {PROMPT_ENV_VAR: "/nonexistent/prompt.md"}):
        settings = _real_settings()
        with pytest.raises(llm.PromptConfigurationError):
            llm.default_prompt_path(settings)


def test_default_prompt_path_raises_when_configured_path_is_directory(tmp_path):
    with patch.dict(os.environ, {PROMPT_ENV_VAR: str(tmp_path)}):
        settings = _real_settings()
        with pytest.raises(llm.PromptConfigurationError):
            llm.default_prompt_path(settings)


def test_prompt_configuration_error_is_not_retryable():
    assert llm.PromptConfigurationError.failure_code is FailureCode.CONFIGURATION_ERROR
    assert llm.PromptConfigurationError.retryable is False


def test_adapter_initialization_raises_when_env_not_configured():
    with patch.dict(os.environ, {PROMPT_ENV_VAR: ""}):
        settings = _real_settings()
        with pytest.raises(llm.PromptConfigurationError):
            llm.LLMInterpretationAdapter(client=_FakeClient(_FakeCompletions()), settings=settings)


def test_adapter_uses_prompt_file_configured_by_env(tmp_path):
    """env var → 실제 Settings → 어댑터가 해당 파일을 system message로 쓰는 경로."""
    prompt_file = _write_prompt(tmp_path / "adapter-prompt.md", "ADAPTER ENV MARKER")
    completions = _FakeCompletions(responses=[_FakeResponse(SELECT_JSON)])
    with patch.dict(os.environ, {PROMPT_ENV_VAR: str(prompt_file)}):
        settings = _real_settings()
        adapter = llm.LLMInterpretationAdapter(
            client=_FakeClient(completions), settings=settings
        )
    _run(adapter.interpret("반동", job_id="r1", session_id="session-1", attempt=1, max_attempts=3))
    sent = completions.calls[0]["messages"][0]["content"]
    assert sent.startswith("ADAPTER ENV MARKER\n")
    assert "Include answer_text" in sent


def test_openai_client_has_max_retries_zero():
    with patch("openai.AsyncOpenAI") as fake_client_cls:
        adapter = llm.LLMInterpretationAdapter(
            system_message=SYSTEM_EXAMPLE,
            user_template=TEMPLATE_EXAMPLE,
        )
    call_kwargs = fake_client_cls.call_args.kwargs
    assert call_kwargs.get("max_retries") == 0
    assert call_kwargs.get("timeout") == 180.0


def test_settings_reads_llm_model_and_timeout_from_env():
    with patch.dict(os.environ, {"LLM_MODEL": "vendor/model-x", "LLM_TIMEOUT_SECONDS": "72"}):
        settings = _real_settings()
    assert settings.llm_model == "vendor/model-x"
    assert settings.llm_timeout_seconds == 72.0


def test_settings_defaults_to_spec_model_and_180_second_timeout(monkeypatch):
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.delenv("LLM_TIMEOUT_SECONDS", raising=False)
    settings = _real_settings()
    assert settings.llm_model == "openai/gpt-4o-mini"
    assert settings.llm_timeout_seconds == 180.0


def test_adapter_uses_llm_model_env_value(monkeypatch):
    with patch.dict(os.environ, {"LLM_MODEL": "vendor/model-x"}):
        settings = _real_settings()
    completions = _FakeCompletions(responses=[_FakeResponse(SELECT_JSON)])
    adapter = _adapter(completions, settings=settings)
    _run(adapter.interpret("반동", job_id="j1", session_id="s1", attempt=1, max_attempts=3))
    assert completions.calls[0]["model"] == "vendor/model-x"


def test_openrouter_spec_and_deployment_use_llm_model_and_180_second_timeout():
    spec = (REPO_ROOT / "docs/specs/openrouter-llm-adapter.md").read_text(encoding="utf-8")
    env_example = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    deployment = (REPO_ROOT / "DEPLOYMENT.md").read_text(encoding="utf-8")
    cloudbuild = (REPO_ROOT / "cloudbuild.yaml").read_text(encoding="utf-8")

    assert "`LLM_MODEL`" in spec
    assert "180초" in spec
    assert "LLM_MODEL=openai/gpt-4.1-mini" in env_example
    assert "LLM_TIMEOUT_SECONDS=180" in env_example
    assert "LLM_MODEL=openai/gpt-4.1-mini" in deployment
    assert "LLM_TIMEOUT_SECONDS=180" in deployment
    api_deploy = cloudbuild.split('id: "deploy-api"', maxsplit=1)[1].split('\n\n  # 5.', maxsplit=1)[0]
    mcp_deploy = cloudbuild.split('id: "deploy-mcp"', maxsplit=1)[1].split('id: "deploy-api"', maxsplit=1)[0]
    assert "LLM_MODEL=openai/gpt-4.1-mini" in api_deploy
    assert "INTERPRETER_PROMPT_VERSION=uhkegryo-interpreter-v4" in api_deploy
    assert "LLM_TIMEOUT_SECONDS=180" in api_deploy
    assert "LLM_MODEL" not in mcp_deploy
    assert "LLM_TIMEOUT_SECONDS" not in mcp_deploy


def test_env_example_declares_concrete_local_prompt_path():
    """.env.example에 주석이 아니라 실제 설정값이 있어야 한다."""
    env_example = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    assignments = [
        line.split("=", 1)[1].strip()
        for line in env_example.splitlines()
        if line.strip().startswith(f"{PROMPT_ENV_VAR}=")
    ]
    assert assignments == ["./prompts/uhkegryo-interpreter-v4.md"]
    assert "INTERPRETER_PROMPT_VERSION=uhkegryo-interpreter-v4" in env_example


def test_docker_deploy_path_consistency():
    assert REPO_PROMPT_FILE.exists()
    dockerfile = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "COPY prompts/uhkegryo-interpreter-v4.md /app/prompts/uhkegryo-interpreter-v4.md" in dockerfile
    cloudbuild = (REPO_ROOT / "cloudbuild.yaml").read_text(encoding="utf-8")
    assert "INTERPRETER_PROMPT_PATH=/app/prompts/uhkegryo-interpreter-v4.md" in cloudbuild
    env_example = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    assert f"{PROMPT_ENV_VAR}=" in env_example
    assert "./prompts/uhkegryo-interpreter-v4.md" in env_example


def test_cloudbuild_hosts_mcp_next_to_searxng_and_grants_api_invoker():
    cloudbuild = (REPO_ROOT / "cloudbuild.yaml").read_text(encoding="utf-8")
    api_deploy = cloudbuild.split('id: "deploy-api"', maxsplit=1)[1].split('\n\n  # 5.', maxsplit=1)[0]
    mcp_deploy = cloudbuild.split('id: "deploy-mcp"', maxsplit=1)[1].split('id: "deploy-api"', maxsplit=1)[0]
    allow_host = cloudbuild.split('id: "allow-mcp-cloud-run-host"', maxsplit=1)[1].split('id: "bind-mcp-invoker"', maxsplit=1)[0]

    assert "--service-account=${_MCP_CALLER_SA}@${PROJECT_ID}.iam.gserviceaccount.com" in api_deploy
    assert 'waitFor: ["push-image", "push-searxng-image", "get-api-ingress-container", "deploy-mcp"]' in api_deploy
    assert "--container=searxng" in mcp_deploy
    assert "--container=${ingress_container}" in mcp_deploy
    assert 'if [ "${ingress_container}" = "__default__" ]' in mcp_deploy
    assert "services replace /workspace/mcp-deploy.json" in mcp_deploy
    assert "--depends-on=searxng" in mcp_deploy
    assert "SEARXNG_BASE_URL=http://localhost:8080" in mcp_deploy
    assert "value(status.url)" in allow_host
    assert "MCP_ALLOWED_HOST=${mcp_host}" in allow_host
    assert 'waitFor: ["deploy-mcp", "deploy-api"]' in allow_host
    assert 'ingress_container="$(cat /workspace/api-ingress-container)"' in allow_host
    assert '--container="${ingress_container}"' in allow_host
    assert "MCP_BASE_URL=${mcp_url}/mcp" in allow_host


@pytest.mark.parametrize("file_version,configured", [("v0", "v4"), ("v4", "v0"), ("v0", "v0"), ("v4", "v4")])
def test_prompt_declaration_matches_version_even_when_renamed(tmp_path, file_version, configured):
    prompt = tmp_path / "custom-name.md"
    prompt.write_text((REPO_ROOT / f"prompts/uhkegryo-interpreter-{file_version}.md").read_text(encoding="utf-8"), encoding="utf-8")
    settings = _real_settings().model_copy(update={"interpreter_prompt_version": f"uhkegryo-interpreter-{configured}"})
    if file_version != configured:
        with pytest.raises(llm.PromptConfigurationError, match="INTERPRETER_PROMPT_VERSION"):
            llm.LLMInterpretationAdapter(settings=settings, prompt_path=prompt, client=object())
    else:
        assert llm.LLMInterpretationAdapter(settings=settings, prompt_path=prompt, client=object()).prompt_version.endswith(configured)
