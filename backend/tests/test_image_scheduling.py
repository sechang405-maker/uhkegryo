import asyncio
from types import SimpleNamespace
import pytest
from backend.schemas.enums import Role, PinStatus
from backend.schemas.models import PinResult
from backend.services.pinterest_widget import PinterestWidgetClient
from backend.services.response_assembler import RoleSearchOutcome
from backend.services.agent_worker import AgentJobWorker
from backend.services import agent_worker


def test_eighty_cold_pins_with_shared_readers_keep_identity_and_bounds():
    async def run():
        active = peak = calls = 0
        async def load(url):
            nonlocal active, peak, calls
            active += 1
            peak = max(peak, active)
            calls += 1
            try:
                await asyncio.sleep(.02)
                pin_id = url.rsplit('=', 1)[1]
                return {'data': [{'id': pin_id, 'images': {'ok': {'url': f'https://i.pinimg.com/{pin_id}.jpg', 'width': 1, 'height': 1}}}]}
            finally:
                active -= 1
        client = PinterestWidgetClient(json_loader=load, shared_readers=True, timeout_seconds=.1)
        outcomes = [RoleSearchOutcome(role=Role.POSE, pins=[PinResult(pin_id=str(i), pin_url=f'https://www.pinterest.com/pin/{i}/', status=PinStatus.AVAILABLE) for i in range(n, n+8)]) for n in range(0,80,8)]
        async def reader():
            return await asyncio.gather(*(client.enrich_outcome(o) for o in outcomes))
        first, second = await asyncio.gather(reader(), reader())
        assert [p.pin_id for o in first for p in o.pins] == [str(i) for i in range(80)]
        assert all(p.status == PinStatus.AVAILABLE for reader_result in (first, second) for o in reader_result for p in o.pins)
        assert calls == 80
        assert peak <= 8
        await client.aclose()
    asyncio.run(run())


def test_transport_failure_is_retryable_unavailable():
    async def load(url):
        raise TimeoutError()
    pin = PinResult(pin_id='1', pin_url='https://www.pinterest.com/pin/1/', status=PinStatus.AVAILABLE)
    result = asyncio.run(PinterestWidgetClient(json_loader=load).enrich_outcome(RoleSearchOutcome(role=Role.POSE,pins=[pin])))
    assert result.pins[0].status.value == 'unavailable'
    assert result.pins[0].thumbnail_url is None


def test_ten_local_cards_get_full_io_budget_after_slot(monkeypatch):
    async def run():
        active = peak = 0
        class Provider:
            def __init__(self, **kwargs): pass
            async def search(self, role, fragments):
                nonlocal active, peak
                active += 1
                peak = max(peak, active)
                try:
                    await asyncio.sleep(.04)
                    return RoleSearchOutcome(role=role)
                finally: active -= 1
        monkeypatch.setattr(agent_worker, 'SearXNGPinterestSearchProvider', Provider)
        monkeypatch.setattr(agent_worker, 'LOCAL_SEARCH_IO_TIMEOUT_SECONDS', .1, raising=False)
        real_timeout = asyncio.timeout
        monkeypatch.setattr(asyncio, 'timeout', lambda seconds: real_timeout(.1 if seconds == 25 else seconds))
        worker = AgentJobWorker(None,None,tracer=SimpleNamespace(),local_search_url='http://localhost')
        resolution = SimpleNamespace(terms=[SimpleNamespace(selection=SimpleNamespace(role=Role.POSE,term_id=str(i)),card={'query_fragments':['pose']}) for i in range(10)])
        result = await worker._local_search_outcomes(resolution,{})
        assert list(result) == [str(i) for i in range(10)]
        assert all(o.code is None for o in result.values())
        assert peak <= 3
    asyncio.run(run())


def test_only_verified_missing_is_deleted_and_total_budget_is_bounded():
    async def run():
        async def load(url):
            pin_id = url.rsplit('=',1)[1]
            if pin_id == '1': return {'data': []}
            if pin_id == '2': return {'data': [{'id': '2', 'images': 'malformed'}]}
            await asyncio.Event().wait()
        pins = [PinResult(pin_id=str(i),pin_url=f'https://www.pinterest.com/pin/{i}/',status=PinStatus.AVAILABLE) for i in range(1,4)]
        client = PinterestWidgetClient(json_loader=load,total_timeout_seconds=.05)
        result = await asyncio.wait_for(client.enrich_outcome(RoleSearchOutcome(role=Role.POSE,pins=pins)),1)
        assert [p.status.value for p in result.pins] == ['unavailable','unavailable','unavailable']
        assert not client._slots.locked()
    asyncio.run(run())


def test_local_total_deadline_preserves_finished_cards_and_cancels_tail(monkeypatch):
    async def run():
        active = 0
        class Provider:
            def __init__(self, **kwargs): pass
            async def search(self, role, fragments):
                nonlocal active
                active += 1
                try:
                    if fragments == ('0',): return RoleSearchOutcome(role=role)
                    await asyncio.Event().wait()
                finally: active -= 1
        monkeypatch.setattr(agent_worker, 'SearXNGPinterestSearchProvider', Provider)
        monkeypatch.setattr(agent_worker, 'LOCAL_SEARCH_TOTAL_TIMEOUT_SECONDS', .05)
        worker = AgentJobWorker(None,None,tracer=SimpleNamespace(),local_search_url='http://localhost')
        terms = [SimpleNamespace(selection=SimpleNamespace(role=Role.POSE,term_id=str(i)),card={'query_fragments':[str(i)]}) for i in range(10)]
        result = await asyncio.wait_for(worker._local_search_outcomes(SimpleNamespace(terms=terms),{}),1)
        assert result['0'].code is None
        assert all(result[str(i)].code.value == 'PIN_SEARCH_UNAVAILABLE' for i in range(1,10))
        assert active == 0
        assert not worker._search_slots.locked()
    asyncio.run(run())


def test_unavailable_api_contract_requires_null_thumbnail():
    from pydantic import ValidationError
    pin = PinResult(pin_id='1',pin_url='https://www.pinterest.com/pin/1/',status='unavailable')
    assert pin.model_dump(mode='json')['status'] == 'unavailable'
    assert pin.model_dump(mode='json')['thumbnail_url'] is None
    with pytest.raises(ValidationError):
        PinResult(pin_id='1',pin_url='https://www.pinterest.com/pin/1/',status='unavailable',thumbnail_url='https://i.pinimg.com/1.jpg')


def test_shutdown_closes_admission_before_waiting_consumers_can_start():
    async def run():
        started = asyncio.Event()
        release = asyncio.Event()
        calls = []
        active = 0
        async def load(url):
            nonlocal active
            calls.append(url)
            active += 1
            started.set()
            try:
                await release.wait()
                pin_id = url.rsplit('=',1)[1]
                return {'data':[{'id':pin_id,'images':{'ok':{'url':f'https://i.pinimg.com/{pin_id}.jpg','width':1,'height':1}}}]}
            finally: active -= 1
        client = PinterestWidgetClient(json_loader=load,shared_readers=True,max_pending=1,concurrency=2)
        pins = [PinResult(pin_id=str(i),pin_url=f'https://www.pinterest.com/pin/{i}/',status=PinStatus.AVAILABLE) for i in range(1,4)]
        request = asyncio.create_task(client.enrich_outcome(RoleSearchOutcome(role=Role.POSE,pins=pins)))
        await asyncio.wait_for(started.wait(),1)
        # First fetch is admitted; another distinct Pin waits for capacity.
        await asyncio.sleep(0)
        assert len(client._inflight) == 1
        await client.aclose()
        release.set()
        result = await asyncio.wait_for(request,1)
        assert len(calls) == 1
        assert all(pin.status is PinStatus.UNAVAILABLE for pin in result.pins)
        assert active == 0
        assert not client._inflight and not client._cache
        after = await client.enrich_outcome(RoleSearchOutcome(role=Role.POSE,pins=pins))
        assert all(pin.status is PinStatus.UNAVAILABLE for pin in after.pins)
        assert len(calls) == 1
        await client.aclose()
    asyncio.run(run())
