from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
import os
from types import SimpleNamespace

import httpx
import openai
import pytest

from backend.services.llm import LLMInterpretationAdapter, LLMUpstreamUnavailable
from backend.services.portfolio_budget import (
    PortfolioBudgetExceeded,
    PortfolioLLMCallBudget,
)
from backend.services.openrouter_free_models import (
    OpenRouterFreeModelVerificationError,
    verify_free_model_catalog,
    verify_selected_free_model,
)


class _Pool:
    def __init__(self, rows):
        self.rows = list(rows)
        self.calls = []

    async def fetchrow(self, query, *args):
        self.calls.append((query, args))
        return self.rows.pop(0)


def test_budget_uses_one_atomic_upsert_and_fails_closed_at_limit():
    pool = _Pool([{"used_calls": 40}, None])
    budget = PortfolioLLMCallBudget(pool, limit=40)

    assert asyncio.run(budget.reserve()) == 40
    with pytest.raises(PortfolioBudgetExceeded):
        asyncio.run(budget.reserve())

    query, args = pool.calls[0]
    normalized = " ".join(query.split()).upper()
    assert "INSERT INTO PORTFOLIO_LLM_DAILY_USAGE" in normalized
    assert "ON CONFLICT (USAGE_DATE) DO UPDATE" in normalized
    assert "WHERE PORTFOLIO_LLM_DAILY_USAGE.USED_CALLS < $2" in normalized
    assert "RETURNING USED_CALLS" in normalized
    assert args[1] == 40


class _Completions:
    def __init__(self):
        self.calls = 0

    async def create(self, **kwargs):
        self.calls += 1
        return SimpleNamespace(usage=None)


class _Client:
    def __init__(self, completions):
        self.chat = SimpleNamespace(completions=completions)


def _settings():
    return SimpleNamespace(
        interpreter_prompt_version="test-version",
        llm_model="example/model:free",
        llm_max_tokens=128,
        is_portfolio=True,
    )


def test_adapter_reserves_immediately_before_each_external_call():
    completions = _Completions()
    reservations = []

    async def reserve():
        reservations.append("reserved")
        return len(reservations)

    adapter = LLMInterpretationAdapter(
        client=_Client(completions), settings=_settings(),
        system_message="system", user_template="{request_text}",
        call_reserver=reserve,
    )
    asyncio.run(adapter._request([{"role": "user", "content": "one"}]))
    asyncio.run(adapter._request([{"role": "user", "content": "two"}]))

    assert reservations == ["reserved", "reserved"]
    assert completions.calls == 2


def test_exhausted_budget_never_calls_provider_and_is_not_retryable():
    completions = _Completions()

    async def refuse():
        raise PortfolioBudgetExceeded

    adapter = LLMInterpretationAdapter(
        client=_Client(completions), settings=_settings(),
        system_message="system", user_template="{request_text}",
        call_reserver=refuse,
    )
    with pytest.raises(Exception) as error:
        asyncio.run(adapter._request([{"role": "user", "content": "blocked"}]))

    assert type(error.value).__name__ == "PortfolioDailyLimitReached"
    assert error.value.retryable is False
    assert completions.calls == 0


def test_personal_term_transport_forwards_same_call_reserver(monkeypatch):
    from backend.services import llm, personal_term_generator

    captured = {}

    class _Adapter:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(llm, "LLMInterpretationAdapter", _Adapter)
    monkeypatch.setattr(
        "backend.shared.config.get_settings",
        lambda: SimpleNamespace(llm_backend="openrouter"),
    )

    async def reserve():
        return 1

    personal_term_generator.ExistingLLMTransport(call_reserver=reserve)
    assert captured["call_reserver"] is reserve


@pytest.mark.parametrize("status", [402, 429])
def test_portfolio_free_tier_refusal_is_terminal(status):
    request = httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions")
    if status == 429:
        error = openai.RateLimitError(
            "free limit", response=httpx.Response(status, request=request), body=None
        )
    else:
        error = openai.APIStatusError(
            "payment required", response=httpx.Response(status, request=request), body=None
        )

    class _FailingCompletions:
        async def create(self, **kwargs):
            raise error

    adapter = LLMInterpretationAdapter(
        client=_Client(_FailingCompletions()), settings=_settings(),
        system_message="system", user_template="{request_text}",
    )
    with pytest.raises(Exception) as caught:
        asyncio.run(adapter._request([{"role": "user", "content": "blocked"}]))
    assert type(caught.value).__name__ == "PortfolioFreeTierUnavailable"
    assert caught.value.retryable is False


def test_migration_caps_database_counter_at_forty_under_concurrency():
    from backend.tests.test_conversation_sessions import database_case

    async def case(pool):
        budget = PortfolioLLMCallBudget(pool, limit=40)

        async def reserve_once():
            try:
                await budget.reserve()
                return True
            except PortfolioBudgetExceeded:
                return False

        outcomes = await asyncio.gather(*(reserve_once() for _ in range(60)))
        assert sum(outcomes) == 40
        assert await pool.fetchval(
            "SELECT used_calls FROM portfolio_llm_daily_usage"
        ) == 40

    asyncio.run(database_case(case))


def test_database_counter_has_independent_utc_date_boundaries():
    from backend.tests.test_conversation_sessions import database_case

    async def case(pool):
        budget = PortfolioLLMCallBudget(pool, limit=40)
        before = datetime(2026, 10, 27, 23, 59, 59, tzinfo=timezone.utc)
        after = datetime(2026, 10, 28, 0, 0, 0, tzinfo=timezone.utc)
        assert await budget.reserve(now=before) == 1
        assert await budget.reserve(now=before) == 2
        assert await budget.reserve(now=after) == 1
        rows = await pool.fetch(
            "SELECT usage_date,used_calls FROM portfolio_llm_daily_usage ORDER BY usage_date"
        )
        assert [(str(row["usage_date"]), row["used_calls"]) for row in rows] == [
            ("2026-10-27", 2),
            ("2026-10-28", 1),
        ]

    asyncio.run(database_case(case))


def test_retry_attempt_and_personal_term_call_share_database_counter():
    from backend.services.personal_term_generator import ExistingLLMTransport
    from backend.tests.test_conversation_sessions import database_case

    async def case(pool):
        budget = PortfolioLLMCallBudget(pool, limit=40)
        request = httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions")
        responses = [
            openai.InternalServerError(
                "temporary", response=httpx.Response(500, request=request), body=None
            ),
            SimpleNamespace(
                usage=None,
                choices=[SimpleNamespace(message=SimpleNamespace(content='{"ok":true}'))],
            ),
            SimpleNamespace(
                usage=None,
                choices=[SimpleNamespace(message=SimpleNamespace(content='{"term":true}'))],
            ),
        ]

        class _SequencedCompletions:
            async def create(self, **kwargs):
                result = responses.pop(0)
                if isinstance(result, Exception):
                    raise result
                return result

        adapter = LLMInterpretationAdapter(
            client=_Client(_SequencedCompletions()), settings=_settings(),
            system_message="system", user_template="{request_text}",
            call_reserver=budget.reserve,
        )
        with pytest.raises(LLMUpstreamUnavailable):
            await adapter._request([{"role": "user", "content": "attempt one"}])
        await adapter._request([{"role": "user", "content": "retry"}])
        transport = ExistingLLMTransport(adapter=adapter)
        assert await transport.generate(
            [{"role": "user", "content": "personal term"}], {"type": "json_object"}
        ) == '{"term":true}'
        assert await pool.fetchval(
            "SELECT used_calls FROM portfolio_llm_daily_usage"
        ) == 3

    asyncio.run(database_case(case))


def test_openrouter_catalog_accepts_only_zero_priced_allowlisted_models():
    payload = {"data": [{
        "id": "example/model:free",
        "pricing": {
            "prompt": "0", "completion": "0", "request": "0",
            "image": "0", "web_search": "0",
        },
    }]}
    verify_free_model_catalog(payload, ("example/model:free",))

    payload["data"][0]["pricing"]["completion"] = "0.000001"
    with pytest.raises(OpenRouterFreeModelVerificationError):
        verify_free_model_catalog(payload, ("example/model:free",))


@pytest.mark.parametrize("field,value", [
    ("request", "0.01"),
    ("image", "0.0001"),
    ("web_search", "0.1"),
    ("internal_reasoning", "unknown"),
    ("input_cache_read", None),
])
def test_openrouter_catalog_rejects_any_positive_or_unknown_price(field, value):
    payload = {"data": [{
        "id": "example/model:free",
        "pricing": {"prompt": "0", "completion": "0", "request": "0", field: value},
    }]}
    with pytest.raises(OpenRouterFreeModelVerificationError):
        verify_free_model_catalog(payload, ("example/model:free",))


def test_openrouter_catalog_requires_explicit_request_pricing():
    payload = {"data": [{
        "id": "example/model:free",
        "pricing": {"prompt": "0", "completion": "0"},
    }]}
    with pytest.raises(OpenRouterFreeModelVerificationError):
        verify_free_model_catalog(payload, ("example/model:free",))


def test_selected_model_preflight_reads_fresh_catalog_and_exact_model(tmp_path):
    payload = {"data": [{
        "id": "example/model:free",
        "pricing": {"prompt": "0", "completion": "0", "request": "0"},
    }]}
    catalog_path = tmp_path / "openrouter-models.json"
    catalog_path.write_text(json.dumps(payload), encoding="utf-8")
    settings = SimpleNamespace(
        llm_model="example/model:free",
        portfolio_free_models=("example/model:free", "other/model:free"),
        portfolio_model_catalog_path=str(catalog_path),
        portfolio_model_catalog_max_age_seconds=3600,
    )
    verify_selected_free_model(settings)


def test_selected_model_preflight_rejects_model_outside_allowlist_without_file():
    settings = SimpleNamespace(
        llm_model="paid/model",
        portfolio_free_models=("example/model:free",),
        portfolio_model_catalog_path="missing.json",
        portfolio_model_catalog_max_age_seconds=3600,
    )
    with pytest.raises(OpenRouterFreeModelVerificationError):
        verify_selected_free_model(settings)


def test_selected_model_preflight_rejects_stale_catalog(tmp_path):
    catalog_path = tmp_path / "openrouter-models.json"
    catalog_path.write_text(json.dumps({"data": [{
        "id": "example/model:free",
        "pricing": {"prompt": "0", "completion": "0", "request": "0"},
    }]}), encoding="utf-8")
    os.utime(catalog_path, (1, 1))
    settings = SimpleNamespace(
        llm_model="example/model:free",
        portfolio_free_models=("example/model:free",),
        portfolio_model_catalog_path=str(catalog_path),
        portfolio_model_catalog_max_age_seconds=3600,
    )
    with pytest.raises(OpenRouterFreeModelVerificationError, match="stale"):
        verify_selected_free_model(settings)


@pytest.mark.parametrize("payload", [
    {"data": []},
    {"data": [{"id": "example/model:free", "pricing": {"prompt": "0"}}]},
    {"data": [{"id": "example/model:free", "pricing": {"prompt": "free", "completion": "0"}}]},
])
def test_openrouter_catalog_verification_fails_closed(payload):
    with pytest.raises(OpenRouterFreeModelVerificationError):
        verify_free_model_catalog(payload, ("example/model:free",))
