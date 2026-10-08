from searxng.patch_pinterest_engine import patch_engine_file, patch_engine_source


def test_pinterest_engine_uses_pin_url_when_pin_has_external_source_link():
    source = '''
url=result.get("link") or f"{base_url}/pin/{result['id']}/",
'''

    patched = patch_engine_source(source)

    assert patched == '''
url=f"{base_url}/pin/{result['id']}/",
'''


def test_pinterest_engine_patch_fails_if_upstream_source_changes():
    try:
        patch_engine_source('url=result.get("link")')
    except RuntimeError as error:
        assert str(error) == "Unexpected SearXNG Pinterest engine source"
    else:
        raise AssertionError("Expected source drift to fail the SearXNG image build")


def test_pinterest_engine_patch_removes_stale_bytecode(tmp_path):
    engine_path = tmp_path / "searx" / "engines" / "pinterest.py"
    engine_path.parent.mkdir(parents=True)
    engine_path.write_text(
        'url=result.get("link") or f"{base_url}/pin/{result[\'id\']}/",',
        encoding="utf-8",
    )
    cache_path = engine_path.parent / "__pycache__" / "pinterest.cpython-314.pyc"
    cache_path.parent.mkdir()
    cache_path.write_bytes(b"stale bytecode")

    patch_engine_file(engine_path)

    assert 'url=f"{base_url}/pin/{result[\'id\']}/",' in engine_path.read_text(encoding="utf-8")
    assert not cache_path.exists()
