"""Fail-closed, database-atomic budget for portfolio LLM provider calls."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


class PortfolioBudgetExceeded(Exception):
    """The UTC-day provider-call budget has no remaining reservation."""


class PortfolioLLMCallBudget:
    def __init__(self, pool: Any, *, limit: int = 40) -> None:
        self._pool = pool
        self._limit = limit

    async def reserve(self, *, now: datetime | None = None) -> int:
        usage_date = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).date()
        row = await self._pool.fetchrow(
            """
            INSERT INTO portfolio_llm_daily_usage(usage_date, used_calls, updated_at)
            VALUES($1, 1, now())
            ON CONFLICT (usage_date) DO UPDATE
            SET used_calls = portfolio_llm_daily_usage.used_calls + 1,
                updated_at = now()
            WHERE portfolio_llm_daily_usage.used_calls < $2
            RETURNING used_calls
            """,
            usage_date,
            self._limit,
        )
        if row is None:
            raise PortfolioBudgetExceeded
        return int(row["used_calls"])
