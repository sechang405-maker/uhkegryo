"""Task 12: Widget image selection, isolation, and response-only rehydration."""

import asyncio
import json
from fastapi.testclient import TestClient

from backend.main import app
from backend.routes import agent as agent_route
from backend.schemas.enums import AgentStatus, JobStatus, PinStatus, Role
from backend.schemas.models import AgentResult, JobEnvelope, PinResult, ReferencePlan, TermResult
from backend.services.job_repository import _dump
from backend.services.pinterest_widget import PinterestWidgetClient, PinterestWidgetProvider, WIDGET_URL
from backend.services.pinterest_provider import FakePinterestProvider
from backend.services.searxng_pinterest_search import SearXNGPinterestSearchProvider
from backend.services.response_assembler import RoleSearchOutcome
from backend.shared.auth import SESSION_COOKIE_NAME


def _pin(pin_id: str) -> PinResult:
    return PinResult(pin_id=pin_id, pin_url=f"https://www.pinterest.com/pin/{pin_id}/",
                     status=PinStatus.AVAILABLE)


def _payload(pin_id: str, images: dict) -> dict:
    return {"data": [{"id": pin_id, "images": images, "description": "private body",
                      "pinner": {"name": "private author"}}]}


def test_widget_selects_largest_image_and_preserves_order_and_limit():
    calls = []

    async def load(url):
        calls.append(url)
        pin_id = url.rsplit("=", 1)[-1]
        return _payload(pin_id, {
            "small": {"url": f"https://i.pinimg.com/{pin_id}-small.jpg", "width": 100, "height": 100},
            "large": {"url": f"https://i.pinimg.com/{pin_id}-large.jpg", "width": 300, "height": 200},
        })

    original = RoleSearchOutcome(role=Role.POSE, pins=[_pin(str(i)) for i in range(1, 10)])
    result = asyncio.run(PinterestWidgetClient(json_loader=load).enrich_outcome(original))

    assert [pin.pin_id for pin in result.pins] == [str(i) for i in range(1, 9)]
    assert [pin.pin_url for pin in result.pins] == [pin.pin_url for pin in original.pins[:8]]
    assert all(pin.thumbnail_url == f"https://i.pinimg.com/{pin.pin_id}-large.jpg"
               for pin in result.pins)
    assert calls == [WIDGET_URL.format(pin_id=i) for i in range(1, 9)]
    assert all(pin.thumbnail_url is None for pin in original.pins)
    assert "private body" not in json.dumps([pin.model_dump() for pin in result.pins])


def test_widget_failure_or_missing_image_only_deletes_affected_pin():
    async def load(url):
        pin_id = url.rsplit("=", 1)[-1]
        if pin_id == "2":
            raise TimeoutError("private upstream details")
        if pin_id == "3":
            return _payload(pin_id, {"bad": {"url": "http://untrusted", "width": 50, "height": 50}})
        if pin_id == "4":
            return {"data": "malformed"}
        return _payload(pin_id, {"ok": {"url": "https://i.pinimg.com/ok.jpg",
                                         "width": 50, "height": 50}})

    outcome = RoleSearchOutcome(role=Role.BODY, pins=[_pin("1"), _pin("2"), _pin("3"), _pin("4")])
    result = asyncio.run(PinterestWidgetClient(json_loader=load).enrich_outcome(outcome))
    assert [pin.status for pin in result.pins] == [PinStatus.AVAILABLE] + [PinStatus.DELETED] * 3
    assert [pin.thumbnail_url for pin in result.pins] == ["https://i.pinimg.com/ok.jpg"] + [None] * 3
    assert all(pin.status is PinStatus.AVAILABLE for pin in outcome.pins)


def test_widget_provider_preserves_search_contract():
    async def load(_url):
        return _payload("7", {"image": {"url": "https://i.pinimg.com/7.jpg",
                                       "width": 100, "height": 100}})

    source = FakePinterestProvider({Role.VIEW: RoleSearchOutcome(role=Role.VIEW, pins=[_pin("7")])})
    provider = PinterestWidgetProvider(source, PinterestWidgetClient(json_loader=load))
    result = asyncio.run(provider.search(Role.VIEW, ("low angle",)))
    assert source.calls[0].query_fragments == ("low angle",)
    assert result.pins[0].thumbnail_url == "https://i.pinimg.com/7.jpg"


def test_searxng_search_returns_thumbnail_and_original_pin_url_together():
    search_calls = []

    async def search_load(url, params):
        search_calls.append((url, params))
        return {"results": [{"url": "https://www.pinterest.com/pin/77/"}]}

    async def widget_load(url):
        return _payload("77", {"image": {
            "url": "https://i.pinimg.com/77.jpg", "width": 200, "height": 100,
        }})

    source = SearXNGPinterestSearchProvider(
        base_url="http://searxng:8080", json_loader=search_load,
    )
    provider = PinterestWidgetProvider(source, PinterestWidgetClient(json_loader=widget_load))
    outcome = asyncio.run(provider.search(Role.POSE, ("standing pose",)))
    pin = outcome.pins[0]

    assert search_calls[0][1]["q"] == "!pin standing pose drawing"
    assert pin.pin_url == "https://www.pinterest.com/pin/77/"
    assert pin.thumbnail_url == "https://i.pinimg.com/77.jpg"


def _completed_job() -> JobEnvelope:
    term = TermResult(role=Role.POSE, term_id="pose_shift", label_ko="자세", label_en="pose",
                      plain_meaning_ko="설명", search_url="https://www.pinterest.com/search/",
                      pins=[_pin("11")])
    result = AgentResult(agent_status=AgentStatus.SUCCESS,
                         reference_plan=ReferencePlan(terms=[term]))
    return JobEnvelope(job_id="job-1", session_id="session-1", job_status=JobStatus.COMPLETED,
                       attempt=1, max_attempts=3, result=result)


def test_get_job_requeries_widget_without_persisting_thumbnail(monkeypatch):
    stored = _completed_job()
    calls = []

    async def load(url):
        calls.append(url)
        return _payload("11", {"image": {"url": f"https://i.pinimg.com/{len(calls)}.jpg",
                                           "width": 100, "height": 100}})

    class Sessions:
        async def has_owner(self, token):
            return token == "valid"
        async def session_for_job(self, token, job_id):
            return "session-1"

    class Jobs:
        async def get(self, *, session_id, job_id):
            assert (session_id, job_id) == ("session-1", "00000000-0000-0000-0000-000000000001")
            return stored

    async def repositories():
        return Sessions(), Jobs()

    monkeypatch.setattr(agent_route, "get_repositories", repositories)
    monkeypatch.setattr(agent_route, "get_widget_client",
                        lambda: PinterestWidgetClient(json_loader=load))
    with TestClient(app) as client:
        assert client.get("/api/jobs/job-1").status_code == 401
        client.cookies.set(SESSION_COOKIE_NAME, "valid")
        first = client.get("/api/jobs/00000000-0000-0000-0000-000000000001").json()
        second = client.get("/api/jobs/00000000-0000-0000-0000-000000000001").json()

    first_pin = first["result"]["reference_plan"]["terms"][0]["pins"][0]
    second_pin = second["result"]["reference_plan"]["terms"][0]["pins"][0]
    assert first_pin["thumbnail_url"] == "https://i.pinimg.com/1.jpg"
    assert second_pin["thumbnail_url"] == "https://i.pinimg.com/2.jpg"
    assert calls == [WIDGET_URL.format(pin_id="11")] * 2
    assert stored.result.reference_plan.terms[0].pins[0].thumbnail_url is None
    assert "thumbnail_url" not in _dump(stored.result)
    assert "thumbnail_url" not in _dump(AgentResult.model_validate(first["result"]))


def test_noncompleted_job_skips_widget():
    async def forbidden(_url):
        raise AssertionError("widget must not be queried")

    queued = JobEnvelope(job_id="job-2", session_id="session-1", job_status=JobStatus.QUEUED,
                         attempt=1, max_attempts=3, poll_after_ms=1000)
    client = PinterestWidgetClient(json_loader=forbidden)
    assert asyncio.run(client.enrich_job(queued)) is queued
