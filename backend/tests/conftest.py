"""T17 결정론 서비스 테스트 공용 fixture."""
import os

# get_settings()가 Settings()를 실행할 때 database_url 필수이므로 테스트 기본값을 먼저 잡아둔다.
os.environ.setdefault("DATABASE_URL", "sqlite:///./t17-test.db")

import json  # noqa: E402
from pathlib import Path  # noqa: E402

import pytest  # noqa: E402

from backend.schemas.enums import Role  # noqa: E402
from backend.services.catalog_repository import CatalogSnapshot  # noqa: E402


@pytest.fixture
def card_factory():
    """resolver·assembler 테스트용 최소 활성 카드 제조기."""

    def make(
        term_id: str,
        role: str = "pose",
        query_fragments: list[str] | None = None,
        source_answer_draft: str = "초안 설명",
        look_for: list[str] | None = None,
        label_ko: str = "라벨",
        label_en: str = "label",
        requires_all_of: list[str] | None = None,
        requires_any_of: list[str] | None = None,
        runtime_eligible: bool = True,
        mvp_status: str = "active_in_current_contract",
        source_type: str = "team_card",
    ) -> dict:
        if query_fragments is None:
            query_fragments = [term_id.replace("_", " ")]
        return {
            "term_id": term_id,
            "role": role,
            "label_ko": label_ko,
            "label_en": label_en,
            "query_fragments": query_fragments,
            "look_for": look_for if look_for is not None else [label_ko + " 관찰 지점"],
            "confidence_gate": {"require_any": ["단서 A"], "do_not_infer_from": ["단서 B"]},
            "requires_all_of": requires_all_of or [],
            "requires_any_of": requires_any_of or [],
            "runtime_eligible": runtime_eligible,
            "mvp_status": mvp_status,
            "source_type": source_type,
            "source_answer_draft": source_answer_draft,
        }

    return make


@pytest.fixture
def snapshot_factory():
    """검증 없이 CatalogSnapshot을 직접 구성하는 제조기 (resolver/assembler 단위 테스트용)."""

    def make(
        cards: list[dict],
        feedback: dict[str, dict] | None = None,
        dsd: tuple[str, ...] = (),
        roles_order: tuple[Role, ...] | None = None,
    ) -> CatalogSnapshot:
        active = {c["term_id"]: dict(c) for c in cards}
        role_terms: dict[Role, list[str]] = {}
        for c in cards:
            role = Role(c["role"])
            role_terms.setdefault(role, []).append(c["term_id"])
        return CatalogSnapshot(
            dataset_version="t17-test",
            active_cards=active,
            role_terms=role_terms,
            roles_order=roles_order or tuple(Role),
            feedback=feedback or {},
            direct_search_disabled=frozenset(dsd),
        )

    return make


@pytest.fixture
def write_catalog(tmp_path: Path):
    """repository 테스트용 index.json + 역할 JSON 생성기."""

    def write(categories: list[tuple[str, str]], role_cards: dict[str, list[dict]], **index_extra) -> Path:
        index = {
            "dataset_name": "t17-test-catalog",
            "dataset_version": "0.0-test",
            "status": "fully_reviewed_runtime_approved",
            "categories": [{"role": role, "file": f"{role}.json"} for role, _ in categories],
            "pinterest_search_contract": {
                "input_source": "선택된 카드의 query_fragments",
                "allow_llm_freeform_query": False,
                "direct_search_disabled_term_ids": [],
            },
        }
        index.update(index_extra)
        (tmp_path / "index.json").write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")
        for role, _ in categories:
            payload = {"role": role, "cards": role_cards.get(role, [])}
            (tmp_path / f"{role}.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return tmp_path

    return write