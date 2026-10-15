"""Fake transport only: shared public metadata, separate cancellation owners."""
import asyncio
import json
from types import SimpleNamespace

import httpx

from backend.schemas.enums import Role, PinStatus
from backend.services.response_assembler import RoleSearchOutcome
from backend.tests.test_pinterest_widget import _pin, _completed_job


def test_worker_result_and_card_search_share_only_public_urls():
    async def run():
        from backend.services.public_http import PublicHttpResources
        requests = []
        def transport(request):
            requests.append(request)
            if request.url.path == '/search':
                return httpx.Response(200, json={'results': [{'url': 'https://www.pinterest.com/pin/11/'}]})
            return httpx.Response(200, json={'data': [{'id': '11', 'description': 'private upstream',
                'images': {'a': {'url': 'https://i.pinimg.com/11.jpg', 'width': 1, 'height': 1}}}]})
        http = httpx.AsyncClient(transport=httpx.MockTransport(transport))
        resources = PublicHttpResources(client=http)
        worker = await resources.worker_widget.enrich_outcome(RoleSearchOutcome(role=Role.POSE, pins=[_pin('11')]))
        stored = _completed_job()
        result = await resources.result_widget.enrich_job(stored)
        other = stored.model_copy(deep=True, update={'session_id': 'other-owner'})
        assert (await resources.result_widget.enrich_job(other)).session_id == 'other-owner'
        card = await resources.search_provider('http://search', 'drawing').search(Role.POSE, ('standing',))
        assert worker.pins[0].thumbnail_url == result.result.reference_plan.terms[0].pins[0].thumbnail_url == card.pins[0].thumbnail_url
        assert len(requests) == 2  # one Widget request plus one search request
        assert stored.result.reference_plan.terms[0].pins[0].thumbnail_url is None
        assert 'private' not in json.dumps(list(resources.result_widget._cache.items()))
        assert all(isinstance(value[1], str) for value in resources.result_widget._cache.values())
        await resources.aclose()
        await resources.aclose()
        assert http.is_closed
        assert not resources.result_widget._cache
    asyncio.run(run())


def test_lifespan_wires_routes_and_worker_and_closes_once(monkeypatch):
    import backend.main as main
    from backend.routes import agent, term_search
    from backend.services.public_http import PublicHttpResources, current_resources
    async def run():
        close_calls = []
        class Transport(httpx.AsyncBaseTransport):
            async def handle_async_request(self, request):
                return httpx.Response(200, json={'results': []})
            async def aclose(self):
                close_calls.append(1)
        resources = PublicHttpResources(client=httpx.AsyncClient(transport=Transport()))
        seen = []
        async def worker(snapshot):
            seen.append(current_resources())
            await asyncio.Event().wait()
        monkeypatch.setattr(main, 'PublicHttpResources', lambda: resources)
        monkeypatch.setattr(main, 'run_worker', worker)
        async with main.lifespan(main.app):
            await asyncio.sleep(0)
            assert seen == [resources]
            assert current_resources() is resources
            assert agent.get_widget_client() is resources.result_widget
            provider = term_search.get_search_provider('sketch')
            assert provider._widget is resources.worker_widget
            assert provider._source._json_loader == resources.search_json
        assert current_resources() is None
        assert close_calls == [1]
        await resources.aclose()
        assert close_calls == [1]
    asyncio.run(run())


def test_shared_cache_ttl_lru_across_paths():
    async def run():
        from backend.services.public_http import PublicHttpResources
        now, calls = [0], []
        def transport(request):
            pin = request.url.params['pin_ids']
            calls.append(pin)
            return httpx.Response(200, json={'data': [{'id': pin, 'images': {'a': {
                'url': f'https://i.pinimg.com/{pin}.jpg', 'width': 1, 'height': 1}}}]})
        resources = PublicHttpResources(client=httpx.AsyncClient(transport=httpx.MockTransport(transport)),
            ttl_seconds=10, max_entries=2, clock=lambda: now[0])
        async def get(client, pin):
            return await client.enrich_outcome(RoleSearchOutcome(role=Role.POSE, pins=[_pin(pin)]))
        await get(resources.worker_widget, '1')
        await get(resources.result_widget, '2')
        await get(resources.worker_widget, '1')
        await get(resources.result_widget, '3')
        await get(resources.worker_widget, '2')
        assert calls == ['1', '2', '3', '2']
        now[0] = 10
        await get(resources.result_widget, '2')
        assert calls == ['1', '2', '3', '2', '2']
        await resources.aclose()
    asyncio.run(run())


def test_cancel_job_preserves_reader_and_shutdown_cancels_owned_fetch():
    async def run():
        from backend.services.public_http import PublicHttpResources
        started, gate = asyncio.Event(), asyncio.Event()
        count = active = 0
        async def transport(request):
            nonlocal count, active
            count += 1
            active += 1
            if count == 2:
                started.set()
            try:
                await gate.wait()
                return httpx.Response(200, json={'data': [{'id': '11', 'images': {'a': {
                    'url': 'https://i.pinimg.com/11.jpg', 'width': 1, 'height': 1}}}]})
            finally:
                active -= 1
        resources = PublicHttpResources(client=httpx.AsyncClient(transport=httpx.MockTransport(transport)))
        job = asyncio.create_task(resources.worker_widget.enrich_job(_completed_job()))
        reader = asyncio.create_task(resources.result_widget.enrich_job(_completed_job()))
        await asyncio.wait_for(started.wait(), 1)
        job.cancel()
        await asyncio.gather(job, return_exceptions=True)
        assert active == 1
        gate.set()
        assert (await reader).result.reference_plan.terms[0].pins[0].status is PinStatus.AVAILABLE
        gate.clear()
        resources.result_widget._cache.clear()
        owned = asyncio.create_task(resources.worker_widget.enrich_job(_completed_job()))
        while active == 0:
            await asyncio.sleep(0)
        await resources.aclose()
        await asyncio.gather(owned, return_exceptions=True)
        assert active == 0
        assert resources.http.is_closed
    asyncio.run(run())


def test_real_worker_local_search_uses_shared_transport_and_get_cache():
    async def run():
        from backend.services.agent_worker import AgentJobWorker
        from backend.services.public_http import PublicHttpResources
        calls = []
        def transport(request):
            calls.append(request)
            if request.url.path == '/search':
                assert request.url.params['q'] == '!pin standing drawing'
                return httpx.Response(200, json={'results': [{'url': 'https://pinterest.com/pin/11/'}]})
            return httpx.Response(200, json={'data': [{'id': '11', 'images': {'a': {
                'url': 'https://i.pinimg.com/11.jpg', 'width': 1, 'height': 1}}}]})
        resources = PublicHttpResources(client=httpx.AsyncClient(transport=httpx.MockTransport(transport)))
        worker = AgentJobWorker(None, None, tracer=SimpleNamespace(), local_search_url='http://search',
            widget_client=resources.worker_widget, search_json_loader=resources.search_json)
        resolution = SimpleNamespace(terms=[SimpleNamespace(selection=SimpleNamespace(role=Role.POSE,
            term_id='pose_standing'), card={'query_fragments': ['standing']})])
        outcome = await worker._local_search_outcomes(resolution, {})
        assert outcome['pose_standing'].pins[0].thumbnail_url == 'https://i.pinimg.com/11.jpg'
        await resources.result_widget.enrich_job(_completed_job())
        assert len(calls) == 2
        await resources.aclose()
    asyncio.run(run())


def test_mixed_path_widget_io_keeps_global_eight_slot_bound():
    async def run():
        from backend.services.public_http import PublicHttpResources
        active = peak = calls = 0
        async def transport(request):
            nonlocal active, peak, calls
            calls += 1
            active += 1
            peak = max(peak, active)
            try:
                await asyncio.sleep(.001)
                pin = request.url.params['pin_ids']
                return httpx.Response(200, json={'data': [{'id': pin, 'images': {'a': {
                    'url': f'https://i.pinimg.com/{pin}.jpg', 'width': 1, 'height': 1}}}]})
            finally:
                active -= 1
        resources = PublicHttpResources(client=httpx.AsyncClient(transport=httpx.MockTransport(transport)))
        outputs = await asyncio.gather(*[client.enrich_outcome(RoleSearchOutcome(role=Role.POSE,
            pins=[_pin(str(i)) for i in range(start, start + 8)]))
            for client, start in [(resources.worker_widget, 1), (resources.result_widget, 20)]])
        assert calls == 16 and peak == 8
        assert all(p.status is PinStatus.AVAILABLE for output in outputs for p in output.pins)
        await resources.aclose()
    asyncio.run(run())


def test_shutdown_cancels_search_request_before_transport_close():
    async def run():
        from backend.services.public_http import PublicHttpResources
        started, stopped = asyncio.Event(), asyncio.Event()
        class Transport(httpx.AsyncBaseTransport):
            async def handle_async_request(self, request):
                started.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    stopped.set()
            async def aclose(self):
                assert stopped.is_set()
        resources = PublicHttpResources(client=httpx.AsyncClient(transport=Transport()))
        request = asyncio.create_task(resources.search_provider('http://search').search(Role.POSE, ('standing',)))
        await started.wait()
        await resources.aclose()
        assert request.cancelled()
        assert not resources._search_tasks
    asyncio.run(run())
