"""Pinterest 검색 URL 빌더 (term-card-catalog.md pinterest_search_contract 기준).

검색 입력은 선택된 활성 카드의 `query_fragments`만 조합한다 (`input_source`).
LLM 자유 검색어·일상어·해설 문장은 사용하지 않는다 (allow_llm_freeform_query 등 전부 false).
provider 계약(T16) 확정 전까지 사용할 결정론 기본 템플릿을 제공하며,
provider 확정 시 이 모듈의 템플릿만 교체하면 된다.
"""

from __future__ import annotations

import urllib.parse

SEARCH_SUFFIXES = frozenset({"drawing", "sketch", "mannequinization"})

def build_search_url(
    query_fragments: list[str], base_url: str | None = None, *, suffix: str = "drawing"
) -> str:
    """카드 검색 조각 뒤에 검증된 접미사를 붙여 Pinterest 검색 URL을 만든다."""
    if suffix not in SEARCH_SUFFIXES:
        raise ValueError("지원하지 않는 검색 접미사입니다")
    if not query_fragments:
        raise ValueError("query_fragments는 비어 있을 수 없다")

    if base_url is None:
        from backend.shared.config import get_settings

        base_url = get_settings().pinterest_search_base_url

    query = " ".join(str(fragment) for fragment in query_fragments) + " " + suffix
    base = str(base_url).rstrip("/")
    return f"{base}/?q={urllib.parse.quote_plus(query)}"
