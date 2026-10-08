import asyncio

import pytest

import backend.main as main_module
from backend.services.catalog_repository import CatalogLoadError


def test_api_startup_loads_catalog_once(monkeypatch):
    catalog_snapshot = object()
    calls = []

    monkeypatch.setattr(main_module, "resolve_term_cards_dir", lambda settings: "catalog")
    monkeypatch.setattr(
        main_module,
        "load_catalog",
        lambda path: calls.append(path) or catalog_snapshot,
    )

    async def exercise():
        async with main_module.app.router.lifespan_context(main_module.app):
            assert main_module.app.state.catalog is catalog_snapshot

    asyncio.run(exercise())
    assert calls == ["catalog"]


def test_api_startup_rejects_invalid_catalog(monkeypatch):
    monkeypatch.setattr(main_module, "resolve_term_cards_dir", lambda settings: "catalog")
    monkeypatch.setattr(
        main_module,
        "load_catalog",
        lambda path: (_ for _ in ()).throw(CatalogLoadError("invalid")),
    )

    async def exercise():
        with pytest.raises(RuntimeError, match="CATALOG_INVALID_AT_STARTUP"):
            async with main_module.app.router.lifespan_context(main_module.app):
                pass

    asyncio.run(exercise())
