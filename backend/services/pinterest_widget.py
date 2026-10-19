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
from backend.services.public_pin_urls import is_opaque_pin_id, public_search_image
from backend.services.public_failures import public_failure

WIDGET_URL = "https://widgets.pinterest.com/v3/pidgets/pins/info/?pin_ids={pin_id}"
JsonLoader = Callable[[str], Awaitable[object]]


class WidgetUnavailable(Exception):
    """A transient lookup failure; never evidence that a Pin was deleted."""
    def __init__(self, reason='unavailable', retry_after_seconds=None):
        self.reason, self.retry_after_seconds = reason, retry_after_seconds


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
                 shared_readers: bool = False, total_timeout_seconds: float = 120,
                 public_cache: OrderedDict | None = None,
                 slots: asyncio.Semaphore | None = None) -> None:
        if min(ttl_seconds, max_entries, concurrency, max_pending, timeout_seconds, total_timeout_seconds) <= 0:
            raise ValueError('Widget limits must be positive')
        self._json_loader = json_loader or _load_widget_json
        self._ttl, self._max_entries = ttl_seconds, max_entries
        self._max_pending, self._timeout = max_pending, timeout_seconds
        self._clock = clock
        self._shared_readers = shared_readers
        self._closed = False
        self._slots = slots if slots is not None else asyncio.Semaphore(concurrency)
        self._admission = asyncio.Semaphore(max_pending)
        self._concurrency = concurrency
        self._total_timeout = total_timeout_seconds
        # Only validated public URL strings; never jobs, owners, payloads or image bytes.
        self._cache: OrderedDict[str, tuple[float, str]] = public_cache if public_cache is not None else OrderedDict()
        self._inflight: dict[str, asyncio.Task] = {}
        self._owned_tasks: set[asyncio.Task] = set()
        self._retry_until = OrderedDict()

    async def aclose(self) -> None:
        # Close admission before cancellation releases capacity to queued readers.
        self._closed = True
        tasks = list(self._inflight.values()) + list(self._owned_tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self._inflight.clear()
        self._cache.clear()

    async def enrich_outcome(self, outcome: RoleSearchOutcome) -> RoleSearchOutcome:
        """Return at most eight Pins in their original order without changing the input."""
        pins = await self._enrich_pins(outcome.pins[:8])
        return RoleSearchOutcome(role=outcome.role, pins=pins, code=outcome.code,
                                 search_failure=outcome.search_failure, retryable=outcome.retryable,
                                 retry_after_seconds=outcome.retry_after_seconds)

    async def enrich_job(self, envelope: JobEnvelope) -> JobEnvelope:
        """Rehydrate persisted Pin IDs without persisting thumbnails or whole responses."""
        if envelope.job_status is not JobStatus.COMPLETED or envelope.result is None:
            return envelope
        result = envelope.model_copy(deep=True)
        if result.result is None or result.result.reference_plan is None:
            return result
        terms = result.result.reference_plan.terms
        locations = [(term, index, pin) for term in terms for index, pin in enumerate(term.pins)]
        enriched = await self._enrich_pins([pin for _, _, pin in locations])
        for (term, index, _), pin in zip(locations, enriched):
            term.pins[index] = pin
        return result

    async def _enrich_pins(self, pins):
        # A bounded set of consumers admits work gradually, preserving input order.
        results = [pin.model_copy(update={"thumbnail_url": None, "status": PinStatus.UNAVAILABLE})
                   for pin in pins]
        pending = iter(enumerate(pins))
        async def consume():
            for index, pin in pending:
                results[index] = await self._lookup(pin)
        try:
            async with asyncio.timeout(self._total_timeout):
                async with asyncio.TaskGroup() as group:
                    for _ in range(min(self._concurrency, len(pins))):
                        group.create_task(consume())
        except TimeoutError:
            pass
        return results

    async def _lookup(self, pin: PinResult) -> PinResult:
        # Public search now also returns opaque e1 IDs, unsupported by Widget.
        # Use only its validated public CDN URL in this response/bounded cache.
        # Persisted results still strip thumbnails; expiry is unavailable, not deleted.
        if is_opaque_pin_id(pin.pin_id):
            url = None if self._closed else public_search_image(pin.thumbnail_url)
            cached = self._cache.pop(pin.pin_id, None)
            if url:
                self._cache[pin.pin_id] = (self._clock() + self._ttl, url)
                while len(self._cache) > self._max_entries:
                    self._cache.popitem(last=False)
            elif not self._closed and cached and cached[0] > self._clock():
                self._cache[pin.pin_id] = cached
                url = cached[1]
            return PinResult(pin_id=pin.pin_id, pin_url=pin.pin_url, thumbnail_url=url,
                             status=PinStatus.AVAILABLE if url else PinStatus.UNAVAILABLE,
                             failure_reason=None if url else 'expired')
        url = None
        reason, delay = None, None
        status = PinStatus.DELETED
        if len(pin.pin_id) <= 64 and pin.pin_id.isascii() and pin.pin_id.isdigit():
            try:
                url = await self._url(pin.pin_id)
                status = PinStatus.AVAILABLE if url else PinStatus.DELETED
            except WidgetUnavailable as error:
                reason, delay = error.reason, error.retry_after_seconds
                status = PinStatus.DELETED if reason == 'deleted' else PinStatus.UNAVAILABLE
        return PinResult(pin_id=pin.pin_id, pin_url=pin.pin_url,
                         thumbnail_url=url, status=status, failure_reason=reason,
                         retry_after_seconds=delay)

    async def _url(self, pin_id: str) -> str | None:
        cooldown = self._retry_until.get(pin_id)
        if cooldown and cooldown > self._clock():
            raise WidgetUnavailable('rate_limited', cooldown - self._clock())
        self._retry_until.pop(pin_id, None)
        if self._closed:
            raise WidgetUnavailable()
        cached = self._cache.pop(pin_id, None)
        if cached and cached[0] > self._clock():
            self._cache[pin_id] = cached
            return cached[1]
        if not self._shared_readers:
            # Worker jobs own their fetches: cancelling one job must not cancel another.
            task = asyncio.create_task(self._fetch(pin_id))
            self._owned_tasks.add(task)
            try:
                return await task
            finally:
                self._owned_tasks.discard(task)
        task = self._inflight.get(pin_id)
        if task is None:
            await self._admission.acquire()
            if self._closed:
                self._admission.release()
                raise WidgetUnavailable()
            # Another reader may have admitted or completed this Pin while we waited.
            cached = self._cache.get(pin_id)
            task = self._inflight.get(pin_id)
            if cached and cached[0] > self._clock():
                self._admission.release()
                self._cache.move_to_end(pin_id)
                return cached[1]
            if task is None:
                task = asyncio.create_task(self._fetch(pin_id))
                self._inflight[pin_id] = task
                def finished(done):
                    self._admission.release()
                    # Retrieve unobserved errors if all shielded readers disconnected.
                    if not done.cancelled():
                        done.exception()
                task.add_done_callback(finished)
            else:
                self._admission.release()
        # A disconnected reader must not cancel another reader's shared lookup.
        return await asyncio.shield(task)

    async def _fetch(self, pin_id: str) -> str | None:
        try:
            async with self._slots:
                if self._closed:
                    raise WidgetUnavailable()
                for attempt in range(2):
                    try:
                        async with asyncio.timeout(self._timeout):
                            payload = await self._json_loader(WIDGET_URL.format(pin_id=pin_id))
                        break
                    except Exception as error:
                        reason, retryable, delay = public_failure(error)
                        if delay is not None:
                            self._retry_until[pin_id] = self._clock() + delay
                            while len(self._retry_until) > self._max_entries:
                                self._retry_until.popitem(last=False)
                        if attempt or not retryable or (delay is not None and delay > 2):
                            raise WidgetUnavailable(reason, delay) from error
                        await asyncio.sleep(delay if delay is not None else .25)
                if not isinstance(payload, Mapping) or not isinstance(payload.get("data"), list):
                    raise WidgetUnavailable()
                # Only a well-formed empty result verifies absence. Broken records
                # and unsafe/missing images remain retryable lookup failures.
                data = payload["data"]
                if data and not all(isinstance(item, Mapping) and "id" in item for item in data):
                    raise WidgetUnavailable()
                url = _largest_image(payload, pin_id)
                if data and not url:
                    raise WidgetUnavailable()
            if self._closed:
                raise WidgetUnavailable()
            if url and len(url) <= 4096:
                self._cache[pin_id] = (self._clock() + self._ttl, url)
                while len(self._cache) > self._max_entries:
                    self._cache.popitem(last=False)
                return url
            if url:
                raise WidgetUnavailable()
            return None
        except WidgetUnavailable:
            raise
        except Exception as error:
            raise WidgetUnavailable() from error
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
