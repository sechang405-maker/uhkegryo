"""Server-only Pinterest Widget lookup; thumbnails exist only in returned models."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from time import monotonic
from collections.abc import Awaitable, Callable, Mapping
from urllib.parse import urlparse

import httpx

from backend.schemas.enums import JobStatus, PinStatus, Role
from backend.schemas.models import JobEnvelope, PinResult
from backend.services.pinterest_provider import PinterestProvider
from backend.services.response_assembler import RoleSearchOutcome

WIDGET_URL = "https://widgets.pinterest.com/v3/pidgets/pins/info/?pin_ids={pin_id}"
JsonLoader = Callable[[str], Awaitable[object]]


class PinterestWidgetProvider:
    """Decorate a search provider while keeping its role/fragment contract."""

    def __init__(self, source: PinterestProvider, widget: "PinterestWidgetClient") -> None:
        self._source = source
        self._widget = widget

    async def search(self, role: Role, query_fragments: tuple[str, ...]) -> RoleSearchOutcome:
        return await self._widget.enrich_outcome(await self._source.search(role, query_fragments))


class PinterestWidgetClient:
    def __init__(self, *, json_loader: JsonLoader | None = None,
                 ttl_seconds: float = 60, max_entries: int = 256,
                 concurrency: int = 8, max_pending: int = 64,
                 timeout_seconds: float = 10, clock: Callable[[], float] = monotonic,
                 shared_readers: bool = False) -> None:
        if min(ttl_seconds, max_entries, concurrency, max_pending, timeout_seconds) <= 0:
            raise ValueError('Widget limits must be positive')
        self._json_loader = json_loader or _load_widget_json
        self._ttl, self._max_entries = ttl_seconds, max_entries
        self._max_pending, self._timeout = max_pending, timeout_seconds
        self._clock = clock
        self._shared_readers = shared_readers
        self._slots = asyncio.Semaphore(concurrency)
        # Only validated public URL strings; never jobs, owners, payloads or image bytes.
        self._cache: OrderedDict[str, tuple[float, str]] = OrderedDict()
        self._inflight: dict[str, asyncio.Task] = {}

    async def aclose(self) -> None:
        tasks = list(self._inflight.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self._inflight.clear()
        self._cache.clear()

    async def enrich_outcome(self, outcome: RoleSearchOutcome) -> RoleSearchOutcome:
        """Return at most eight Pins in their original order without changing the input."""
        pins = await asyncio.gather(
            *(self._lookup(pin) for pin in outcome.pins[:8])
        )
        return RoleSearchOutcome(role=outcome.role, pins=pins, code=outcome.code)

    async def enrich_job(self, envelope: JobEnvelope) -> JobEnvelope:
        """Rehydrate persisted Pin IDs without persisting thumbnails or whole responses."""
        if envelope.job_status is not JobStatus.COMPLETED or envelope.result is None:
            return envelope
        result = envelope.model_copy(deep=True)
        if result.result is None or result.result.reference_plan is None:
            return result
        terms = result.result.reference_plan.terms
        locations = [(term, index, pin) for term in terms for index, pin in enumerate(term.pins)]
        enriched = await asyncio.gather(
            *(self._lookup(pin) for _, _, pin in locations)
        )
        for (term, index, _), pin in zip(locations, enriched):
            term.pins[index] = pin
        return result

    async def _lookup(self, pin: PinResult) -> PinResult:
        url = None
        if len(pin.pin_id) <= 64 and pin.pin_id.isascii() and pin.pin_id.isdigit():
            url = await self._url(pin.pin_id)
        return PinResult(
            pin_id=pin.pin_id,
            pin_url=pin.pin_url,
            thumbnail_url=url,
            status=PinStatus.AVAILABLE if url else PinStatus.DELETED,
        )

    async def _url(self, pin_id: str) -> str | None:
        cached = self._cache.pop(pin_id, None)
        if cached and cached[0] > self._clock():
            self._cache[pin_id] = cached
            return cached[1]
        if not self._shared_readers:
            # Worker jobs own their fetches: cancelling one job must not cancel another.
            return await self._fetch(pin_id)
        task = self._inflight.get(pin_id)
        if task is None:
            if len(self._inflight) >= self._max_pending:
                return None  # Transient overload; never cache a failure.
            task = asyncio.create_task(self._fetch(pin_id))
            self._inflight[pin_id] = task
        # A disconnected reader must not cancel another reader's shared lookup.
        return await asyncio.shield(task)

    async def _fetch(self, pin_id: str) -> str | None:
        try:
            async with asyncio.timeout(self._timeout):
                async with self._slots:
                    payload = await self._json_loader(WIDGET_URL.format(pin_id=pin_id))
                url = _largest_image(payload, pin_id)
            if url and len(url) <= 4096:
                self._cache[pin_id] = (self._clock() + self._ttl, url)
                while len(self._cache) > self._max_entries:
                    self._cache.popitem(last=False)
                return url
            return None
        except Exception:
            return None
        finally:
            self._inflight.pop(pin_id, None)


async def _load_widget_json(url: str) -> object:
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.json()


def _largest_image(payload: object, pin_id: str) -> str | None:
    if not isinstance(payload, Mapping) or not isinstance(payload.get("data"), list):
        return None
    for item in payload["data"]:
        if not isinstance(item, Mapping) or str(item.get("id")) != pin_id:
            continue
        images = item.get("images")
        if not isinstance(images, Mapping):
            return None
        best_url, best_area = None, 0
        for image in images.values():
            if not isinstance(image, Mapping):
                continue
            url, width, height = image.get("url"), image.get("width"), image.get("height")
            if not isinstance(url, str):
                continue
            parsed_url = urlparse(url)
            if parsed_url.scheme != "https" or not parsed_url.netloc:
                continue
            if type(width) is not int or type(height) is not int or width <= 0 or height <= 0:
                continue
            area = width * height
            if area > best_area:
                best_url, best_area = url, area
        return best_url
    return None
