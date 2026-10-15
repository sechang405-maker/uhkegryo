"""App-owned HTTP transport and bounded cache of validated public Pin URLs only."""
from __future__ import annotations

import asyncio
from collections import OrderedDict
from time import monotonic
from weakref import WeakKeyDictionary

import httpx

from backend.services.pinterest_widget import PinterestWidgetClient, PinterestWidgetProvider
from backend.services.searxng_pinterest_search import SearXNGPinterestSearchProvider


class PublicHttpResources:
    """Own the supplied/client transport; callers must await aclose after stopping producers."""

    def __init__(self, *, client=None, ttl_seconds=60, max_entries=256, clock=monotonic):
        self.http = client if client is not None else httpx.AsyncClient(
            timeout=15.0, limits=httpx.Limits(max_connections=16, max_keepalive_connections=16))
        self._closed = False
        self._search_tasks = set()
        cache = OrderedDict()
        slots = asyncio.Semaphore(8)
        options = dict(json_loader=self.widget_json, public_cache=cache, slots=slots,
                       ttl_seconds=ttl_seconds, max_entries=max_entries, clock=clock)
        # Shared URLs, but distinct work ownership: cancelling a job cancels its I/O.
        self.worker_widget = PinterestWidgetClient(**options)
        self.result_widget = PinterestWidgetClient(**options, shared_readers=True)

    async def widget_json(self, url):
        if self._closed:
            raise RuntimeError('Public HTTP resources are closed')
        response = await self.http.get(url, timeout=10.0)
        response.raise_for_status()
        return response.json()

    async def search_json(self, url, params):
        if self._closed:
            raise RuntimeError('Public HTTP resources are closed')
        task = asyncio.current_task()
        self._search_tasks.add(task)
        try:
            response = await self.http.get(url, params=params, timeout=15.0, headers={
                'X-Forwarded-For': '127.0.0.1', 'X-Real-IP': '127.0.0.1'})
            response.raise_for_status()
            return response.json()
        finally:
            self._search_tasks.discard(task)

    def search_provider(self, base_url, suffix='drawing', **kwargs):
        return PinterestWidgetProvider(self.raw_search_provider(base_url, suffix, **kwargs), self.worker_widget)

    def raw_search_provider(self, base_url, suffix='drawing', **kwargs):
        return SearXNGPinterestSearchProvider(base_url=base_url, suffix=suffix,
                                             json_loader=self.search_json, **kwargs)

    async def aclose(self):
        if self._closed:
            return
        self._closed = True
        tasks = list(self._search_tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await asyncio.gather(self.worker_widget.aclose(), self.result_widget.aclose())
        await self.http.aclose()


# Normal app lifespan installs/removes its owned resources on its event loop.
# Keeping fallback hooks separate preserves standalone route/provider test injection.
_resources = WeakKeyDictionary()


def current_resources():
    return _resources.get(asyncio.get_running_loop())


def install_resources(resources):
    _resources[asyncio.get_running_loop()] = resources


def remove_resources(resources):
    loop = asyncio.get_running_loop()
    if _resources.get(loop) is resources:
        del _resources[loop]
