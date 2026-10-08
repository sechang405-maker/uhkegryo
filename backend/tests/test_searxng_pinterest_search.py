"""SearXNG Pinterest engine provider contract tests."""

import asyncio
import pytest

from backend.schemas.enums import PinStatus, ReasonCode, Role
from backend.services.searxng_pinterest_search import (
    SearXNGPinterestSearchProvider,
    parse_search_results,
)
from backend.services.failure_mapping import OperationalFailure
from backend.schemas.enums import FailureCode


def test_parse_search_results_keeps_only_unique_pin_urls_in_order():
    pins = parse_search_results({"results": [
        {"url": "https://www.pinterest.com/pin/111/"},
        {"url": "https://example.com/pin/222/"},
        {"url": "https://kr.pinterest.com/pin/333?x=1"},
        {"url": "https://pinterest.com/pin/111"},
        {"url": "https://pinterest.com/pin/idea/444"},
        {"url": "http://pinterest.com/pin/555/"},
        {"url": "https://[invalid/pin/666/"},
    ]})

    assert [(pin.pin_id, pin.pin_url, pin.status) for pin in pins] == [
        ("111", "https://www.pinterest.com/pin/111/", PinStatus.AVAILABLE),
        ("333", "https://www.pinterest.com/pin/333/", PinStatus.AVAILABLE),
    ]


def test_parse_search_results_limits_to_first_eight_unique_pins():
    payload = {"results": [{"url": f"https://pinterest.com/pin/{pin_id}/"}
                            for pin_id in range(1, 11)]}
    assert [pin.pin_id for pin in parse_search_results(payload)] == [str(i) for i in range(1, 9)]


def test_provider_sends_only_pinterest_engine_and_card_query():
    received = []

    async def load(url, params):
        received.append((url, params))
        return {"results": [{"url": "https://pinterest.com/pin/123/"}]}

    outcome = asyncio.run(SearXNGPinterestSearchProvider(
        base_url="http://searxng:8080/", json_loader=load,
    ).search(Role.POSE, ("standing pose", "weight shift reference")))

    assert received == [("http://searxng:8080/search", {
        "q": "!pin standing pose weight shift reference drawing",
        "categories": "images",
        "format": "json",
        "language": "en",
    })]
    assert outcome.role is Role.POSE
    assert [pin.pin_id for pin in outcome.pins] == ["123"]
    assert outcome.code is None


def test_provider_marks_successful_empty_search():
    async def load(url, params):
        return {"results": []}

    outcome = asyncio.run(SearXNGPinterestSearchProvider(
        base_url="http://searxng:8080", json_loader=load,
    ).search(Role.VIEW, ("low angle",)))
    assert outcome.pins == []
    assert outcome.code is ReasonCode.PIN_RESULTS_EMPTY


@pytest.mark.parametrize("payload", [
    {"results": [], "unresponsive_engines": [["pinterest", "CAPTCHA"]]},
    {"results": [{"url": "https://example.com/not-a-pin"}]},
])
def test_provider_does_not_fallback_when_pinterest_fails_or_has_no_valid_pins(payload):
    calls = []

    async def load(url, params):
        calls.append(params["q"])
        return payload

    outcome = asyncio.run(SearXNGPinterestSearchProvider(
        base_url="http://searxng:8080", json_loader=load,
    ).search(Role.POSE, ("standing",)))
    assert len(calls) == 1 and calls[0].startswith("!pin ")
    assert outcome.pins == []
    assert outcome.code is (ReasonCode.PIN_SEARCH_UNAVAILABLE if "unresponsive_engines" in payload
                            else ReasonCode.PIN_RESULTS_EMPTY)


@pytest.mark.parametrize("engine_error", ["timeout", "CAPTCHA", "too many requests"])
def test_provider_marks_pinterest_engine_error_unavailable(engine_error, caplog):
    async def load(url, params):
        assert params["q"].startswith("!pin ")
        return {"results": [], "unresponsive_engines": [["pinterest", engine_error]]}

    outcome = asyncio.run(SearXNGPinterestSearchProvider(
        base_url="http://searxng:8080", json_loader=load,
    ).search(Role.POSE, ("standing",)))

    assert outcome.pins == []
    assert outcome.code is ReasonCode.PIN_SEARCH_UNAVAILABLE
    assert engine_error not in caplog.text


def test_provider_marks_missing_endpoint_unavailable():
    with pytest.raises(OperationalFailure) as error:
        asyncio.run(SearXNGPinterestSearchProvider(base_url="").search(
            Role.BODY, ("slim body",)
        ))
    assert error.value.failure_code is FailureCode.CONFIGURATION_ERROR


def test_provider_marks_invalid_json_shape_unavailable():
    async def load(url, params):
        return {"unexpected": []}

    outcome = asyncio.run(SearXNGPinterestSearchProvider(
        base_url="http://searxng:8080", json_loader=load,
    ).search(Role.POSE, ("standing",)))
    assert outcome.pins == []
    assert outcome.code is ReasonCode.PIN_SEARCH_UNAVAILABLE
