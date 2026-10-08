"""pinterest_search_contract 기준 검색 URL 빌더 테스트."""

import pytest

from backend.services.search_url_builder import build_search_url

BASE = "https://www.pinterest.com/search/pins/"


def test_build_search_url_joins_query_fragments_and_appends_drawing():
    url = build_search_url(["contrapposto pose", "standing reference"], base_url=BASE)
    assert url == "https://www.pinterest.com/search/pins/?q=contrapposto+pose+standing+reference+drawing"


def test_build_search_url_encodes_korean_and_space():
    url = build_search_url(["한복 캐릭터", "pose reference"], base_url=BASE)
    assert url.startswith("https://www.pinterest.com/search/pins/?q=")
    assert (
        url
        == "https://www.pinterest.com/search/pins/?q=%ED%95%9C%EB%B3%B5+%EC%BA%90%EB%A6%AD%ED%84%B0+pose+reference+drawing"
    )


def test_build_search_url_appends_drawing_after_fragments_that_already_contain_drawing():
    url = build_search_url(
        ["gesture drawing", "action line reference"],
        base_url=BASE,
    )
    assert (
        url
        == "https://www.pinterest.com/search/pins/?q=gesture+drawing+action+line+reference+drawing"
    )


def test_build_search_url_rejects_empty():
    with pytest.raises(ValueError):
        build_search_url([], base_url=BASE)


def test_build_search_url_uses_config_default():
    # conftest가 DATABASE_URL을 세팅해두어 config 기본값 경로 검증 가능
    url = build_search_url(["stand weight shift reference"])
    assert url.startswith("https://www.pinterest.com/search/pins/?q=")
    assert url.endswith("stand+weight+shift+reference+drawing")
