"""Build-time patch that keeps Pinterest engine results linked to their Pin."""

from pathlib import Path


ENGINE_PATH = Path("/usr/local/searxng/searx/engines/pinterest.py")
SOURCE_LINK = 'url=result.get("link") or f"{base_url}/pin/{result[\'id\']}/",'
PIN_LINK = 'url=f"{base_url}/pin/{result[\'id\']}/",'


def patch_engine_source(source: str) -> str:
    if source.count(SOURCE_LINK) != 1:
        raise RuntimeError("Unexpected SearXNG Pinterest engine source")
    return source.replace(SOURCE_LINK, PIN_LINK)


def patch_engine_file(engine_path: Path = ENGINE_PATH) -> None:
    source = engine_path.read_text(encoding="utf-8")
    engine_path.write_text(patch_engine_source(source), encoding="utf-8")
    cache_dir = engine_path.parent / "__pycache__"
    for bytecode in cache_dir.glob("pinterest.*.pyc"):
        bytecode.unlink()


def main() -> None:
    patch_engine_file()


if __name__ == "__main__":
    main()
