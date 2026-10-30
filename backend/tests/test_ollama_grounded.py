from pathlib import Path

import pytest

from backend.services.catalog_repository import load_catalog
from backend.services.ollama_grounded import plan_grounded_request


ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def snapshot():
    return load_catalog(ROOT / "docs/domains/illustration-reference/term-cards")


@pytest.mark.parametrize(
    ("request_text", "expected_terms"),
    [
        ("마르고 팔다리가 긴 캐릭터 체형 자료를 찾고 싶어", {"body_slim"}),
        ("한쪽 다리에 체중을 싣고 골반이 기운 자연스러운 서기 자세", {"pose_contrapposto"}),
        ("아래에서 올려다본 채 바닥에 앉아 있는 인물", {"view_low_angle", "pose_sitting"}),
        ("정면에서 머리부터 발끝까지 보이는 캐릭터 자료", {"view_front", "view_full_body"}),
        ("어깨는 넓고 허리와 하체는 좁은 역삼각형 체형", {"body_inverted_triangle"}),
        ("복도 끝 한 점으로 선이 모이는 배경 원근", {"perspective_one_point", "perspective_vanishing_point"}),
    ],
)
def test_planner_selects_literal_catalog_evidence_without_model(
    snapshot, request_text, expected_terms
):
    result = plan_grounded_request(request_text, snapshot)

    assert result.interpretation_state.value == "select_terms"
    assert expected_terms <= {selection.term_id for selection in result.selections}
    assert all(
        evidence in request_text
        for selection in result.selections
        for evidence in selection.evidence
    )


@pytest.mark.parametrize(
    ("request_text", "clarification_type"),
    [
        ("그냥 멋지고 자연스러운 좋은 자세를 찾아줘", "insufficient_visual_evidence"),
        ("한 인물을 완전한 정면이면서 완전한 뒷모습으로 보여줘", "conflicting_constraints"),
        ("사진처럼 좋은 체형 자료가 필요해", "insufficient_visual_evidence"),
    ],
)
def test_planner_clarifies_without_inventing_search_terms(
    snapshot, request_text, clarification_type
):
    result = plan_grounded_request(request_text, snapshot)

    assert result.interpretation_state.value == "needs_clarification"
    assert result.clarification_type.value == clarification_type
    assert result.selections == []
    assert result.answer_text == ""


@pytest.mark.parametrize(
    ("request_text", "expected_terms"),
    [
        ("호리호리하고 팔다리가 길쭉한 인체 레퍼런스", {"body_slim"}),
        ("한쪽 발에 무게를 몰고 골반선이 비스듬한 서기", {"pose_contrapposto"}),
        (
            "의자 끝에 걸터앉아서 상체를 앞으로 숙인 포즈",
            {"pose_sitting_on_edge", "pose_sitting_leaning_forward"},
        ),
    ],
)
def test_planner_preserves_meaning_for_holdout_paraphrases(
    snapshot, request_text, expected_terms
):
    result = plan_grounded_request(request_text, snapshot)

    assert result.interpretation_state.value == "select_terms"
    assert expected_terms <= {selection.term_id for selection in result.selections}


def test_planner_does_not_select_negated_term(snapshot):
    result = plan_grounded_request(
        "마른 체형 말고 어깨가 넓고 허리와 하체가 좁은 실루엣", snapshot
    )

    selected = {selection.term_id for selection in result.selections}
    assert "body_slim" not in selected
    assert "body_inverted_triangle" in selected


def test_planner_clarifies_unknown_colloquial_shape_instead_of_guessing(snapshot):
    result = plan_grounded_request("벌크업한 상체 느낌의 캐릭터를 찾고 싶어", snapshot)

    assert result.interpretation_state.value == "needs_clarification"
    assert result.selections == []
