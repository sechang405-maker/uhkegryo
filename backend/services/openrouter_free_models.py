"""Pure, fail-closed validation for an OpenRouter free-model catalog response.

Fetching the catalog is deliberately outside this module until API/network use is
separately approved.  Callers can validate an already obtained response without
logging or otherwise retaining credentials.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Iterable


class OpenRouterFreeModelVerificationError(Exception):
    """The supplied catalog did not prove every approved model costs zero."""


def verify_free_model_catalog(payload: Any, model_ids: Iterable[str]) -> None:
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list):
        raise OpenRouterFreeModelVerificationError("Model catalog is malformed")
    by_id = {
        row.get("id"): row for row in data
        if isinstance(row, dict) and isinstance(row.get("id"), str)
    }
    for model_id in model_ids:
        row = by_id.get(model_id)
        pricing = row.get("pricing") if isinstance(row, dict) else None
        if not isinstance(pricing, dict) or not {"prompt", "completion"} <= pricing.keys():
            raise OpenRouterFreeModelVerificationError(
                f"Free pricing was not published for {model_id}"
            )
        try:
            prices = tuple(Decimal(str(value)) for value in pricing.values())
        except (InvalidOperation, TypeError, ValueError):
            raise OpenRouterFreeModelVerificationError(
                f"Pricing was not numeric for {model_id}"
            ) from None
        if not prices or any(price != 0 for price in prices):
            raise OpenRouterFreeModelVerificationError(
                f"Non-zero pricing was published for {model_id}"
            )
