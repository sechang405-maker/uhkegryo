from __future__ import annotations

import asyncio
from types import SimpleNamespace

import httpx
import openai
import pytest

from backend.services.llm import LLMInterpretationAdapter
from backend.services.portfolio_budget import (
    PortfolioBudgetExceeded,
    PortfolioLLMCallBudget,
)
from backend.services.openrouter_free_models import (
    OpenRouterFreeModelVerificationError,
    verify_free_model_catalog,
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


@pytest.mark.parametrize("payload", [
    {"data": []},
    {"data": [{"id": "example/model:free", "pricing": {"prompt": "0"}}]},
    {"data": [{"id": "example/model:free", "pricing": {"prompt": "free", "completion": "0"}}]},
])
def test_openrouter_catalog_verification_fails_closed(payload):
    with pytest.raises(OpenRouterFreeModelVerificationError):
        verify_free_model_catalog(payload, ("example/model:free",))
