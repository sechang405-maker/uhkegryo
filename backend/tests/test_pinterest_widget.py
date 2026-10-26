"""Task 12: Widget image selection, isolation, and response-only rehydration."""

import asyncio
import json
from fastapi.testclient import TestClient

from backend.main import app
from backend.routes import agent as agent_route
from backend.schemas.enums import AgentStatus, JobStatus, PinStatus, ReasonCode, Role
from backend.schemas.models import AgentResult, JobEnvelope, PinResult, ReferencePlan, TermResult
from backend.services.job_repository import _dump
from backend.services.pinterest_widget import PinterestWidgetClient, PinterestWidgetProvider, WIDGET_URL
from backend.services.pinterest_provider import FakePinterestProvider
from backend.services.searxng_pinterest_search import SearXNGPinterestSearchProvider, parse_search_results
from backend.services.response_assembler import RoleSearchOutcome
from backend.shared.auth import SESSION_COOKIE_NAME


def _pin(pin_id: str) -> PinResult:
    return PinResult(pin_id=pin_id, pin_url=f"https://www.pinterest.com/pin/{pin_id}/",
                     status=PinStatus.AVAILABLE)


def _payload(pin_id: str, images: dict) -> dict:
    return {"data": [{"id": pin_id, "images": images, "description": "private body",
                      "pinner": {"name": "private author"}}]}


def test_public_opaque_pin_uses_validated_search_image_without_widget_and_expires():
    async def run():
        clock = [0]
        calls = []
        async def search(url, params):
            return {"results": [{"url": "https://www.pinterest.com/pin/e1_public-ABC_123/",
                "img_src": "https://i.pinimg.com/originals/public.jpg"}]}
        async def widget(url):
            calls.append(url)
            raise AssertionError("Widget does not accept opaque search IDs")
        client = PinterestWidgetClient(json_loader=widget, clock=lambda: clock[0])
        source = SearXNGPinterestSearchProvider(base_url="http://localhost:8080", json_loader=search)
        result = await PinterestWidgetProvider(source, client).search(Role.BODY, ("triangle",))
        assert len(result.pins) == 1
        pin = result.pins[0]
        assert pin.pin_id == "e1_public-ABC_123"
        assert pin.thumbnail_url == "https://i.pinimg.com/originals/public.jpg"
        persisted = pin.model_copy(update={"thumbnail_url": None})
        cached = await client.enrich_outcome(RoleSearchOutcome(role=Role.BODY, pins=[persisted]))
        assert cached.pins[0].thumbnail_url == pin.thumbnail_url
        clock[0] = 61
        expired = await client.enrich_outcome(RoleSearchOutcome(role=Role.BODY, pins=[persisted]))
        assert expired.pins[0].status is PinStatus.UNAVAILABLE
        assert expired.pins[0].thumbnail_url is None
        assert not calls
    asyncio.run(run())


def test_opaque_pin_rejects_untrusted_images_and_unsafe_ids():
    for url in ("http://i.pinimg.com/a.jpg", "https://i.pinimg.com.evil.test/a.jpg",
                "https://user@i.pinimg.com/a.jpg", "https://i.pinimg.com:8443/a.jpg",
                "https://127.0.0.1/a.jpg", "data:image/png;base64,AA"):
        pins = parse_search_results(
            {"results": [{"url": "https://www.pinterest.com/pin/e1_public-ABC_123/", "img_src": url}]})
        assert len(pins) == 1
        assert pins[0].thumbnail_url is None
    for pin_id in ("e1_../other", "e1_a%2Fb", "e1_" + "a" * 201, "e2_other"):
        assert not parse_search_results({"results": [{"url": f"https://www.pinterest.com/pin/{pin_id}/"}]})


def test_opaque_search_thumbnail_is_not_persisted():
    job = _completed_job()
    job.result.reference_plan.terms[0].pins = [PinResult(pin_id="e1_public-ABC_123",
        pin_url="https://www.pinterest.com/pin/e1_public-ABC_123/",
        thumbnail_url="https://i.pinimg.com/originals/public.jpg", status=PinStatus.AVAILABLE)]
    saved = _dump(job.result)
    assert "e1_public-ABC_123" in saved
    assert "thumbnail_url" not in saved
    assert "i.pinimg.com" not in saved


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
    assert [pin.status for pin in result.pins] == [PinStatus.AVAILABLE] + [PinStatus.UNAVAILABLE] * 3
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


def test_get_job_reuses_widget_without_persisting_thumbnail(monkeypatch):
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
    widget = PinterestWidgetClient(json_loader=load)
    monkeypatch.setattr(agent_route, "get_widget_client", lambda: widget)
    with TestClient(app) as client:
        assert client.get("/api/jobs/job-1").status_code == 401
        client.cookies.set(SESSION_COOKIE_NAME, "valid")
        first = client.get("/api/jobs/00000000-0000-0000-0000-000000000001").json()
        second = client.get("/api/jobs/00000000-0000-0000-0000-000000000001").json()

    first_pin = first["result"]["reference_plan"]["terms"][0]["pins"][0]
    second_pin = second["result"]["reference_plan"]["terms"][0]["pins"][0]
    assert first_pin["thumbnail_url"] == "https://i.pinimg.com/1.jpg"
    assert second_pin["thumbnail_url"] == "https://i.pinimg.com/1.jpg"
    assert calls == [WIDGET_URL.format(pin_id="11")]
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


def test_shared_widget_client_lifetime():
    async def run():
        first = agent_route.get_widget_client()
        assert agent_route.get_widget_client() is first
        await agent_route.close_widget_client()
        assert agent_route.get_widget_client() is not first
        await agent_route.close_widget_client()
    asyncio.run(run())


def test_cache_expiry_lru_bound_and_no_cross_response_state():
    now = [0.0]
    calls = []
    async def load(url):
        pin_id = url.rsplit('=', 1)[1]
        calls.append(pin_id)
        return _payload(pin_id, {'image': {'url': f'https://i.pinimg.com/{pin_id}.jpg', 'width': 1, 'height': 1}})
    async def run():
        client = PinterestWidgetClient(json_loader=load, ttl_seconds=10, max_entries=2, clock=lambda: now[0])
        a = _completed_job()
        b = a.model_copy(deep=True, update={'job_id':'other-job','session_id':'other-owner'})
        b.result.reference_plan.terms[0].pins[0].pin_url = 'https://www.pinterest.com/pin/11/?owner=other'
        first = await client.enrich_job(a)
        second = await client.enrich_job(b)
        assert second.session_id == 'other-owner'
        assert second.result.reference_plan.terms[0].pins[0].pin_url.endswith('owner=other')
        first.result.reference_plan.terms[0].pins[0].thumbnail_url = 'https://changed.invalid/'
        assert (await client.enrich_job(a)).result.reference_plan.terms[0].pins[0].thumbnail_url.endswith('/11.jpg')
        assert calls == ['11']
        now[0] = 10
        await client.enrich_job(a)
        assert calls == ['11', '11']
        for pin_id in ('12','13'):
            await client.enrich_outcome(RoleSearchOutcome(role=Role.BODY,pins=[_pin(pin_id)]))
        assert len(client._cache) == 2
        await client.enrich_job(a)
        assert calls == ['11','11','12','13','11']
        assert a.result.reference_plan.terms[0].pins[0].thumbnail_url is None
        assert all(isinstance(value[1], str) for value in client._cache.values())
    asyncio.run(run())


def test_concurrent_requests_coalesce_limit_and_cancel_one_waiter():
    async def run():
        gate, started = asyncio.Event(), asyncio.Event()
        active = peak = calls = 0
        async def load(url):
            nonlocal active, peak, calls
            calls += 1
            active += 1
            peak = max(peak, active)
            started.set()
            try:
                await gate.wait()
                pin_id=url.rsplit('=',1)[1]
                return _payload(pin_id, {'image':{'url':f'https://i.pinimg.com/{pin_id}.jpg','width':1,'height':1}})
            finally:
                active -= 1
        client = PinterestWidgetClient(json_loader=load, concurrency=2, max_pending=3, shared_readers=True)
        first=asyncio.create_task(client.enrich_job(_completed_job()))
        await started.wait()
        second=asyncio.create_task(client.enrich_job(_completed_job()))
        await asyncio.sleep(0)
        first.cancel()
        await asyncio.gather(first, return_exceptions=True)
        more=asyncio.create_task(client.enrich_outcome(RoleSearchOutcome(role=Role.BODY,pins=[_pin(str(i)) for i in range(20,28)])))
        for _ in range(5):
            await asyncio.sleep(0)
        assert len(client._inflight) <= 3
        assert peak <= 2
        gate.set()
        result, overflow = await asyncio.gather(second,more)
        assert result.result.reference_plan.terms[0].pins[0].status is PinStatus.AVAILABLE
        assert calls == 9
        assert all(p.status is PinStatus.AVAILABLE for p in overflow.pins)
        assert not client._inflight
        await client.aclose()
        assert not client._cache
    asyncio.run(run())


def test_failure_timeout_and_invalid_payload_are_not_cached():
    async def run():
        attempts=0
        async def load(_url):
            nonlocal attempts
            attempts+=1
            if attempts == 1:
                raise RuntimeError('private upstream details')
            if attempts == 2:
                await asyncio.Event().wait()
            if attempts == 3:
                return _payload('11', {'image':{'url':'http://unsafe.invalid/','width':1,'height':1}})
            return _payload('11', {'image':{'url':'https://i.pinimg.com/ok.jpg','width':1,'height':1}})
        client= PinterestWidgetClient(json_loader=load, timeout_seconds=.01)
        # Timeout now retries once; the malformed third response remains uncached.
        for expected in (PinStatus.UNAVAILABLE, PinStatus.UNAVAILABLE):
            result=await client.enrich_job(_completed_job())
            assert result.result.reference_plan.terms[0].pins[0].status is expected
            assert not client._cache and not client._inflight
        result=await client.enrich_job(_completed_job())
        assert result.result.reference_plan.terms[0].pins[0].status is PinStatus.AVAILABLE
        assert attempts == 4
    asyncio.run(run())


def test_completed_job_reports_partial_and_total_image_hydration_failures():
    async def run():
        responses = {
            "11": _payload("11", {"image": {
                "url": "https://i.pinimg.com/11.jpg", "width": 100, "height": 100,
            }}),
            "12": {"data": []},
        }

        async def load(url):
            return responses[url.rsplit("=", 1)[-1]]

        job = _completed_job()
        job.result.reference_plan.terms[0].pins.append(_pin("12"))
        client = PinterestWidgetClient(json_loader=load)

        partial = await client.enrich_job(job)
        term = partial.result.reference_plan.terms[0]
        assert term.reason_codes == [ReasonCode.PIN_IMAGES_PARTIAL]
        assert [pin.status for pin in term.pins] == [PinStatus.AVAILABLE, PinStatus.UNAVAILABLE]
        assert partial.result.agent_status is AgentStatus.SUCCESS

        responses["11"] = {"data": []}
        client._cache.clear()
        unavailable = await client.enrich_job(job)
        term = unavailable.result.reference_plan.terms[0]
        assert term.reason_codes == [ReasonCode.PIN_IMAGES_UNAVAILABLE]
        assert all(pin.status is PinStatus.UNAVAILABLE for pin in term.pins)
        assert unavailable.result.agent_status is AgentStatus.SUCCESS

        responses["11"] = _payload("11", {"image": {
            "url": "https://i.pinimg.com/11-recovered.jpg", "width": 100, "height": 100,
        }})
        responses["12"] = _payload("12", {"image": {
            "url": "https://i.pinimg.com/12-recovered.jpg", "width": 100, "height": 100,
        }})
        recovered = await client.enrich_job(job)
        term = recovered.result.reference_plan.terms[0]
        assert term.reason_codes == []
        assert all(pin.status is PinStatus.AVAILABLE for pin in term.pins)

    asyncio.run(run())


def test_concurrent_gets_share_public_lookup_but_keep_owner_results(monkeypatch):
    import httpx
    from backend.services.job_repository import JobNotFound
    ids = {'owner-a':'00000000-0000-0000-0000-000000000001',
           'owner-b':'00000000-0000-0000-0000-000000000002'}
    class Sessions:
        async def has_owner(self, token):
            return token in ids
        async def session_for_job(self, token, job_id):
            if ids[token] != job_id:
                raise JobNotFound
            return token
    class Jobs:
        async def get(self, *, session_id, job_id):
            job = _completed_job().model_copy(deep=True, update={'job_id':job_id,'session_id':session_id})
            job.result.answer_text = 'Private answer for ' + session_id
            return job
    async def repositories():
        return Sessions(), Jobs()
    monkeypatch.setattr(agent_route, 'get_repositories', repositories)
    async def run():
        calls=[]
        async def load(url):
            calls.append(url)
            await asyncio.sleep(.01)
            return _payload('11', {'image':{'url':'https://i.pinimg.com/public.jpg','width':1,'height':1}})
        widget = PinterestWidgetClient(json_loader=load, shared_readers=True)
        monkeypatch.setattr(agent_route, 'PinterestWidgetClient', lambda **kwargs: widget)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
            async def get(owner, job_id):
                return await client.get('/api/jobs/'+job_id,headers={'Cookie':SESSION_COOKIE_NAME+'='+owner})
            responses = await asyncio.gather(*(get(owner,ids[owner]) for owner in list(ids)*5))
            assert all(r.status_code == 200 for r in responses)
            for owner, response in zip(list(ids)*5,responses):
                assert response.json()['session_id'] == owner
                assert response.json()['result']['answer_text'] == 'Private answer for '+owner
            assert len(calls) == 1
            denied = await get('owner-b',ids['owner-a'])
            assert denied.status_code == 404
            assert len(calls) == 1
        await agent_route.close_widget_client()
    asyncio.run(run())


def test_invalid_ids_and_oversized_urls_do_not_enter_cache():
    async def run():
        calls=[]
        async def load(url):
            calls.append(url)
            return _payload('11', {'image':{'url':'https://i.pinimg.com/'+('a'*4096),'width':1,'height':1}})
        client= PinterestWidgetClient(json_loader=load)
        result=await client.enrich_outcome(RoleSearchOutcome(role=Role.BODY,pins=[_pin('../other'),_pin('1'*65),_pin('11')]))
        assert all(p.thumbnail_url is None for p in result.pins)
        assert calls == [WIDGET_URL.format(pin_id='11')]
        assert not client._cache
    asyncio.run(run())


def test_owned_request_cancellation_and_shared_shutdown_stop_fetches():
    async def run(shared):
        started, stopped = asyncio.Event(), asyncio.Event()
        async def load(_url):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                stopped.set()
        client= PinterestWidgetClient(json_loader=load, shared_readers=shared)
        request=asyncio.create_task(client.enrich_job(_completed_job()))
        await started.wait()
        if shared:
            await client.aclose()
        else:
            request.cancel()
        await asyncio.gather(request, return_exceptions=True)
        assert stopped.is_set()
        assert not client._inflight and not client._cache
    asyncio.run(run(False))
    asyncio.run(run(True))


def test_owned_job_cancellation_cannot_cancel_another_job_same_pin():
    async def run():
        both_started, gate = asyncio.Event(), asyncio.Event()
        calls = 0
        async def load(_url):
            nonlocal calls
            calls += 1
            if calls == 2:
                both_started.set()
            await gate.wait()
            return _payload('11', {'image':{'url':'https://i.pinimg.com/ok.jpg','width':1,'height':1}})
        client = PinterestWidgetClient(json_loader=load)
        first = asyncio.create_task(client.enrich_job(_completed_job()))
        second = asyncio.create_task(client.enrich_job(_completed_job()))
        await asyncio.wait_for(both_started.wait(), 1)
        first.cancel()
        await asyncio.gather(first, return_exceptions=True)
        gate.set()
        result = await second
        assert result.result.reference_plan.terms[0].pins[0].status is PinStatus.AVAILABLE
        assert calls == 2
    asyncio.run(run())
