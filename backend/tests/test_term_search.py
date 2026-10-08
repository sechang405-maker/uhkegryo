"""HTTP acceptance tests for term-search-api.md (no external calls)."""
import asyncio
import copy
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend import main
from backend.routes import agent, term_search
from backend.schemas.enums import FailureCode, ReasonCode, Role
from backend.services.failure_mapping import OperationalFailure
from backend.services.llm import LLMInterpretationAdapter
from backend.services.pinterest_widget import PinterestWidgetClient, PinterestWidgetProvider
from backend.services.response_assembler import RoleSearchOutcome
from backend.services.searxng_pinterest_search import SearXNGPinterestSearchProvider
from backend.services.search_url_builder import build_search_url
from backend.services.job_trace import JobTracer


@pytest.fixture
def search_setup(monkeypatch, card_factory, snapshot_factory):
    cards = [card_factory("pose_standing", query_fragments=["standing pose", "gesture drawing"]),
             card_factory("pose_blocked")]
    snapshot = snapshot_factory(cards, dsd=("pose_blocked",), feedback={"pose_standing": {
        "plain_meaning_ko": "서 있는 자세", "selection_reason_template_ko": "선 자세 참고",
        "reference_checkpoints_ko": ["지지하는 다리"],
    }})
    state = SimpleNamespace(queries=[], widgets=[], payload={"results": [
        {"url": f"https://pinterest.com/pin/{i}/"} for i in range(1, 11)]})

    async def load(url, params):
        state.queries.append(params)
        return state.payload

    async def widget(url):
        state.widgets.append(url)
        pin_id = url.rsplit("=", 1)[1]
        return {"data": [{"id": pin_id, "images": {"large": {
            "url": f"https://i.pinimg.com/{pin_id}.jpg", "width": 100, "height": 200}}}]}

    def forbidden(*args, **kwargs):
        pytest.fail("term-search must not call DB, session, job, or LLM")

    monkeypatch.setattr(agent, "get_repositories", forbidden)
    monkeypatch.setattr(LLMInterpretationAdapter, "interpret", forbidden)
    monkeypatch.setattr(JobTracer, "from_settings", forbidden)
    monkeypatch.setattr(app.state, "catalog", snapshot, raising=False)
    monkeypatch.setattr(app.state, "term_search_slots", asyncio.Semaphore(2), raising=False)
    monkeypatch.setattr(term_search, "get_search_provider", lambda suffix: PinterestWidgetProvider(
        SearXNGPinterestSearchProvider(base_url="http://searxng:8080", json_loader=load, suffix=suffix),
        PinterestWidgetClient(json_loader=widget)))
    return state


@pytest.mark.parametrize("suffix", [None, "drawing", "sketch", "mannequinization"])
def test_ac01_real_provider_and_url_use_same_suffix(search_setup, suffix):
    before = copy.deepcopy(app.state.catalog)
    payload = {"term_id": "pose_standing", **({"suffix": suffix} if suffix else {})}
    response = TestClient(app).post("/api/term-search", json=payload)
    assert response.status_code == 200
    result = response.json()
    query = f"standing pose gesture drawing {suffix or 'drawing'}"
    assert search_setup.queries[0]["q"] == f"!pin {query}"
    assert parse_qs(urlparse(result["search_url"]).query)["q"] == [query]
    assert (result["term_id"], result["role"], result["plain_meaning_ko"]) == (
        "pose_standing", "pose", "서 있는 자세")
    assert result["selection_reason"] == "선 자세 참고"
    assert result["reference_checkpoints"] == ["지지하는 다리"]
    assert [pin["pin_id"] for pin in result["pins"]] == [str(i) for i in range(1, 9)]
    assert all(pin["thumbnail_url"] and pin["status"] == "available" for pin in result["pins"])
    assert response.headers["cache-control"] == "no-store"
    assert "set-cookie" not in response.headers
    assert app.state.catalog == before


@pytest.mark.parametrize("payload,status", [
    ({"term_id": "missing"}, 404), ({"term_id": "pose_blocked"}, 409),
    ({"term_id": "pose_standing", "suffix": "https://evil.example"}, 422),
    ({"term_id": "pose_standing", "query": "arbitrary"}, 422),
    ({"term_id": ""}, 422), ({"term_id": "x" * 121}, 422),
    ({"term_id": 1}, 422), ({}, 422),
])
def test_ac02_invalid_requests_do_not_search(search_setup, payload, status):
    assert TestClient(app).post("/api/term-search", json=payload).status_code == status
    assert search_setup.queries == search_setup.widgets == []


@pytest.mark.parametrize("payload,code", [
    ({"results": []}, "PIN_RESULTS_EMPTY"),
    ({"results": [], "unresponsive_engines": [["pinterest", "secret-error"]]},
     "PIN_SEARCH_UNAVAILABLE"), ({"bad": "secret-error"}, "PIN_SEARCH_UNAVAILABLE"),
])
def test_ac03_empty_and_failed_search(search_setup, payload, code):
    search_setup.payload = payload
    response = TestClient(app).post("/api/term-search", json={"term_id": "pose_standing"})
    assert response.status_code == 200
    assert response.json()["reason_codes"] == [code]
    assert response.json()["pins"] == []
    assert "secret-error" not in response.text


@pytest.mark.parametrize("failure,code", [
    (OperationalFailure(FailureCode.CONFIGURATION_ERROR, "secret-error"), 503),
    (OperationalFailure(FailureCode.SEARCH_TIMEOUT, "secret-error"), 200),
])
def test_ac04_operational_failure_releases_slot(search_setup, monkeypatch, failure, code):
    async def fail(*args):
        raise failure
    monkeypatch.setattr(term_search, "get_search_provider", lambda suffix: SimpleNamespace(search=fail))
    response = TestClient(app).post("/api/term-search", json={"term_id": "pose_standing"})
    assert response.status_code == code
    assert "secret-error" not in response.text
    assert not app.state.term_search_slots.locked()
    if code == 200:
        assert response.json()["reason_codes"] == ["PIN_SEARCH_UNAVAILABLE"]


@pytest.mark.parametrize("termination", ["complete", "timeout", "cancel"])
def test_ac05_concurrency_limit_and_slot_recovery(search_setup, monkeypatch, termination):
    async def run():
        release, both_started = asyncio.Event(), asyncio.Event()
        entered = 0

        async def block(role, fragments):
            nonlocal entered
            entered += 1
            if entered == 2:
                both_started.set()
            await release.wait()
            return RoleSearchOutcome(role=role, code=ReasonCode.PIN_RESULTS_EMPTY)

        monkeypatch.setattr(term_search, "get_search_provider", lambda suffix: SimpleNamespace(search=block))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            async def post():
                return await client.post("/api/term-search", json={"term_id": "pose_standing"})
            first, second = asyncio.create_task(post()), asyncio.create_task(post())
            await asyncio.wait_for(both_started.wait(), 1)
            busy = await post()
            assert busy.status_code == 429 and busy.headers["retry-after"] == "1"
            assert entered == 2
            if termination == "cancel":
                first.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await first
            release.set()
            await asyncio.gather(first, second, return_exceptions=True)
            if termination == "timeout":
                monkeypatch.setattr(term_search, "SEARCH_TIMEOUT_SECONDS", 0.01)
                release.clear()
                timed_out = await post()
                assert timed_out.json()["reason_codes"] == ["PIN_SEARCH_UNAVAILABLE"]
                release.set()
            assert (await post()).status_code == 200
    asyncio.run(run())


def test_invalid_suffix_rejected_before_provider_io():
    with pytest.raises(ValueError):
        SearXNGPinterestSearchProvider(base_url="http://searxng", suffix="arbitrary")
    with pytest.raises(ValueError):
        build_search_url(["standing"], suffix="arbitrary")


def test_ac04_actual_missing_configuration(search_setup, monkeypatch):
    monkeypatch.setattr(term_search, "get_settings", lambda: SimpleNamespace(searxng_base_url=""))
    monkeypatch.setattr(term_search, "get_search_provider", lambda suffix: PinterestWidgetProvider(
        SearXNGPinterestSearchProvider(base_url=term_search.get_settings().searxng_base_url, suffix=suffix),
        PinterestWidgetClient()))
    response = TestClient(app).post("/api/term-search", json={"term_id": "pose_standing"})
    assert response.status_code == 503
    assert search_setup.queries == search_setup.widgets == []


def test_ac02_inactive_card_is_not_searchable(search_setup):
    app.state.catalog.active_cards.pop("pose_standing")
    response = TestClient(app).post("/api/term-search", json={"term_id": "pose_standing"})
    assert response.status_code == 404
    assert search_setup.queries == search_setup.widgets == []


def test_ac06_application_startup_installs_search_limiter(search_setup, monkeypatch):
    snapshot = app.state.catalog

    async def idle_worker(catalog):
        await asyncio.Event().wait()

    monkeypatch.setattr(main, "load_catalog", lambda path: snapshot)
    monkeypatch.setattr(main, "run_worker", idle_worker)
    with TestClient(app) as client:
        response = client.post("/api/term-search", json={"term_id": "pose_standing"})
        assert response.status_code == 200
        assert "set-cookie" not in response.headers
        assert response.headers["cache-control"] == "no-store"
