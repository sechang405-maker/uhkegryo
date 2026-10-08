"""term-card-catalog.md AC-01~AC-05 기반 카탈로그 repository 테스트."""

import json

import pytest

from backend.services.catalog_repository import CatalogLoadError, load_catalog

FULL_BODY = True  # 역할 파일에 넣는 카드는 전부 활성 필드 검증을 받는다


def _full_card(card_factory, term_id, **overrides):
    """역할 파일에 들어가는 카드는 필수 필드·활성 조건을 모두 채워야 한다."""
    return card_factory(term_id, **overrides)


def test_load_valid_catalog(write_catalog, card_factory):
    cards = {
        "body": [_full_card(card_factory, "body_slim", role="body")],
        "pose": [
            _full_card(card_factory, "pose_sitting", role="pose"),
            _full_card(card_factory, "pose_support_floor", role="pose"),
            _full_card(
                card_factory,
                "pose_half_lotus",
                role="pose",
                requires_all_of=["pose_sitting", "pose_support_floor"],
            ),
        ],
    }
    feedback = {
        "body_slim": {
            "plain_meaning_ko": "날씬한 체형",
            "selection_reason_template_ko": "입력의 마른 몸 표현에서 해석",
            "reference_checkpoints_ko": ["어깨 폭", "골반 폭"],
        }
    }
    catalog_dir = write_catalog(
        [("body", "body.json"), ("pose", "pose.json")],
        cards,
        active_term_feedback=feedback,
    )

    snapshot = load_catalog(catalog_dir)

    assert snapshot.active_count == 4  # body 1 + pose 3
    assert snapshot.dataset_version == "0.0-test"
    assert [r.value for r in snapshot.roles_order] == ["body", "pose"]
    assert snapshot.role_terms[snapshot.roles_order[0]] == ["body_slim"]
    assert snapshot.get_active("pose_half_lotus")["requires_all_of"] == [
        "pose_sitting",
        "pose_support_floor",
    ]
    assert snapshot.feedback["body_slim"]["plain_meaning_ko"] == "날씬한 체형"


def test_load_valid_catalog_with_dsd_and_disabled_card(write_catalog, card_factory):
    disabled_active = _full_card(card_factory, "pose_action")
    inactive = card_factory("pose_retired", runtime_eligible=False, mvp_status="retired_from_contract")
    cards = {"pose": [_full_card(card_factory, "pose_sitting"), disabled_active, inactive]}
    catalog_dir = write_catalog(
        [("pose", "pose.json")],
        cards,
        pinterest_search_contract={
            "input_source": "선택된 카드의 query_fragments",
            "allow_llm_freeform_query": False,
            "direct_search_disabled_term_ids": ["pose_action"],
        },
    )

    snapshot = load_catalog(catalog_dir)

    assert snapshot.active_count == 2  # 비활성 카드는 제외
    assert snapshot.is_direct_search_disabled("pose_action")
    assert snapshot.get_active("pose_retired") is None


@pytest.mark.parametrize(
    "mutator",
    [
        lambda d: (d / "index.json").unlink(),
        lambda d: (d / "pose.json").unlink(),
    ],
)
def test_fail_closed_for_missing_files(write_catalog, card_factory, tmp_path, mutator):
    catalog_dir = write_catalog(
        [("pose", "pose.json")],
        {"pose": [_full_card(card_factory, "pose_sitting")]},
    )
    mutator(catalog_dir)
    with pytest.raises(CatalogLoadError):
        load_catalog(catalog_dir)


def test_fail_closed_for_json_parse_error(write_catalog, card_factory, tmp_path):
    catalog_dir = write_catalog(
        [("pose", "pose.json")],
        {"pose": [_full_card(card_factory, "pose_sitting")]},
    )
    (catalog_dir / "pose.json").write_text("{ not json", encoding="utf-8")
    with pytest.raises(CatalogLoadError):
        load_catalog(catalog_dir)


def test_fail_closed_for_duplicate_term_id(write_catalog, card_factory):
    cards = {
        "pose": [
            _full_card(card_factory, "pose_sitting"),
            _full_card(card_factory, "pose_sitting"),
        ]
    }
    catalog_dir = write_catalog([("pose", "pose.json")], cards)
    with pytest.raises(CatalogLoadError):
        load_catalog(catalog_dir)


def test_fail_closed_for_missing_required_field(write_catalog, card_factory):
    card = _full_card(card_factory, "pose_sitting")
    del card["confidence_gate"]
    catalog_dir = write_catalog([("pose", "pose.json")], {"pose": [card]})
    with pytest.raises(CatalogLoadError, match="confidence_gate"):
        load_catalog(catalog_dir)


def test_fail_closed_for_empty_query_fragments(write_catalog, card_factory):
    card = _full_card(card_factory, "pose_sitting", query_fragments=[])
    catalog_dir = write_catalog([("pose", "pose.json")], {"pose": [card]})
    with pytest.raises(CatalogLoadError, match="query_fragments"):
        load_catalog(catalog_dir)


def test_fail_closed_for_role_mismatch(write_catalog, card_factory):
    card = _full_card(card_factory, "pose_sitting", role="body")
    catalog_dir = write_catalog([("pose", "pose.json")], {"pose": [card]})
    with pytest.raises(CatalogLoadError, match="role"):
        load_catalog(catalog_dir)


def test_fail_closed_for_dangling_requires_reference(write_catalog, card_factory):
    cards = {
        "pose": [
            _full_card(card_factory, "pose_sitting"),
            _full_card(card_factory, "pose_half_lotus", requires_all_of=["pose_missing"]),
        ]
    }
    catalog_dir = write_catalog([("pose", "pose.json")], cards)
    with pytest.raises(CatalogLoadError, match="requires_\\*"):
        load_catalog(catalog_dir)


def test_fail_closed_for_feedback_id_not_active(write_catalog, card_factory):
    catalog_dir = write_catalog(
        [("pose", "pose.json")],
        {"pose": [_full_card(card_factory, "pose_sitting")]},
        active_term_feedback={
            "body_unknown": {
                "plain_meaning_ko": "x",
                "selection_reason_template_ko": "x",
                "reference_checkpoints_ko": ["x"],
            }
        },
    )
    with pytest.raises(CatalogLoadError):
        load_catalog(catalog_dir)


def test_fail_closed_for_feedback_missing_field(write_catalog, card_factory):
    catalog_dir = write_catalog(
        [("pose", "pose.json")],
        {"pose": [_full_card(card_factory, "pose_sitting")]},
        active_term_feedback={
            "pose_sitting": {
                "plain_meaning_ko": "x",
                "selection_reason_template_ko": "",
                "reference_checkpoints_ko": ["x"],
            }
        },
    )
    with pytest.raises(CatalogLoadError, match="selection_reason_template_ko"):
        load_catalog(catalog_dir)


def test_requires_reference_must_be_active(write_catalog, card_factory):
    """참조 ID가 활성이면 통과, 비활성이면 실패 (구조 무결성 방어)."""
    inactive_ref = card_factory(
        "pose_kneeling", runtime_eligible=False, mvp_status="retired_from_contract"
    )
    cards = {
        "pose": [
            _full_card(card_factory, "pose_sitting"),
            card_factory(
                "pose_seiza", requires_all_of=["pose_sitting", "pose_kneeling"]
            ),
            inactive_ref,
        ]
    }
    catalog_dir = write_catalog([("pose", "pose.json")], cards)
    # 참조 ID pose_kneeling이 활성이 아니므로 로드 실패
    with pytest.raises(CatalogLoadError):
        load_catalog(catalog_dir)