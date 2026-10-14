import asyncio
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from backend.shared.config import Settings
from backend.schemas.enums import Role, ReasonCode
from backend.services.agent_worker import AgentJobWorker
from backend.services.codex_llm import CodexInterpretationAdapter
from backend.services import searxng_pinterest_search, pinterest_widget


def test_codex_accepts_explicit_loopback_search_only():
    base = dict(_env_file=None, database_url='postgresql://u:p@127.0.0.1:55432/test',
                llm_backend='codex-cli', worker_concurrency=1,
                interpreter_prompt_version='uhkegryo-interpreter-v4')
    assert Settings(**base, searxng_base_url='http://127.0.0.1:8080').searxng_base_url
    for url in ('https://remote.example', 'http://user:pass@localhost:8080',
                'http://localhost:8080/?host=remote', 'http://localhost:8080/#x',
                'file:///tmp/search'):
        with pytest.raises(ValueError):
            Settings(**base, searxng_base_url=url)


def test_codex_worker_searches_catalog_without_llm_and_excludes_old_pins(monkeypatch):
    async def load(url, params):
        assert url == 'http://127.0.0.1:8080/search'
        assert params['q'] == '!pin contrapposto drawing'
        return {'results': [{'url': f'https://www.pinterest.com/pin/{p}/'} for p in (1, 2)]}
    async def widget(url):
        pin = url.rsplit('=', 1)[1]
        return {'data': [{'id': pin, 'images': {'large': {
            'url': f'https://i.pinimg.com/{pin}.jpg', 'width': 100, 'height': 200}}}]}
    monkeypatch.setattr(searxng_pinterest_search, '_load_search_json', load)
    monkeypatch.setattr(pinterest_widget, '_load_widget_json', widget)
    worker = AgentJobWorker(None, None, adapter=object.__new__(CodexInterpretationAdapter),
                            tracer=SimpleNamespace())
    worker._local_search_url = 'http://127.0.0.1:8080'
    worker._widget_client = pinterest_widget.PinterestWidgetClient()
    resolution = SimpleNamespace(terms=[SimpleNamespace(selection=SimpleNamespace(role=Role.POSE),
        card={'query_fragments': ['contrapposto']})])
    outcome = asyncio.run(worker._search_outcomes(resolution, request_text='PRIVATE NEVER SENT',
                                                 exclude_pin_ids={Role.POSE: ['1']}))[Role.POSE]
    assert outcome.code is None
    assert [pin.pin_id for pin in outcome.pins] == ['2']
    assert outcome.pins[0].thumbnail_url == 'https://i.pinimg.com/2.jpg'


def test_codex_term_search_is_available_when_explicitly_configured(monkeypatch, card_factory, snapshot_factory):
    from backend.main import app
    from backend.routes import term_search
    from backend.services.response_assembler import RoleSearchOutcome
    monkeypatch.setattr(term_search, 'get_settings', lambda: SimpleNamespace(
        llm_backend='codex-cli', searxng_base_url='http://127.0.0.1:8080'))
    monkeypatch.setattr(app.state, 'catalog', snapshot_factory([card_factory('pose_standing')]), raising=False)
    monkeypatch.setattr(app.state, 'term_search_slots', asyncio.Semaphore(2), raising=False)
    async def search(role, fragments):
        return RoleSearchOutcome(role=role, code=ReasonCode.PIN_RESULTS_EMPTY)
    monkeypatch.setattr(term_search, 'get_search_provider', lambda suffix: SimpleNamespace(search=search))
    response = TestClient(app).post('/api/term-search', json={'term_id': 'pose_standing'})
    assert response.status_code == 200
    assert response.json()['reason_codes'] == ['PIN_RESULTS_EMPTY']


def test_local_search_failure_and_cancellation_release_slots(monkeypatch):
    async def run():
        worker = AgentJobWorker(None, None, tracer=SimpleNamespace(),
                                local_search_url='http://127.0.0.1:8080')
        resolution = SimpleNamespace(terms=[SimpleNamespace(selection=SimpleNamespace(role=Role.POSE),
            card={'query_fragments': ['contrapposto']})])
        async def unavailable(url, params):
            raise TimeoutError()
        monkeypatch.setattr(searxng_pinterest_search, '_load_search_json', unavailable)
        result = await worker._search_outcomes(resolution, request_text='not sent')
        assert result[Role.POSE].code == ReasonCode.PIN_SEARCH_UNAVAILABLE
        started = asyncio.Event()
        finished = asyncio.Event()
        async def pending(url, params):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                finished.set()
        monkeypatch.setattr(searxng_pinterest_search, '_load_search_json', pending)
        task = asyncio.create_task(worker._search_outcomes(resolution, request_text='not sent'))
        await asyncio.wait_for(started.wait(), 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert finished.is_set()
        assert not worker._search_slots.locked()
    asyncio.run(run())
