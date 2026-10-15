"""Request-local, numeric-only transport observations; no payloads or credentials."""
import asyncio
from contextvars import ContextVar
from contextlib import contextmanager
from time import perf_counter
from types import MappingProxyType

observer_context = ContextVar('codex_transport_observer', default=None)

def emit(observer, values):
    if observer is not None:
        try:
            observer(MappingProxyType(dict(values)))
        except (Exception, asyncio.CancelledError):
            pass

@contextmanager
def stage(values, name):
    values['stage'] = name
    start = perf_counter()
    try:
        yield
    finally:
        values[name + '_ms'] = (perf_counter() - start) * 1000
