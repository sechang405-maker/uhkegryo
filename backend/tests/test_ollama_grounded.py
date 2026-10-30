from pathlib import Path
import json
from types import SimpleNamespace

import pytest

from backend.services.catalog_repository import load_catalog
from backend.services.llm import LLMTimeout
from backend.services.ollama_grounded import (
    GroundedInterpretationResult,
    OllamaGroundedInterpreter,
    plan_grounded_request,
)


ROOT = Path(__file__).resolve().parents[2]


def _run_immediate(coroutine):
    """Drive a coroutine whose fake transport has no asynchronous suspension."""
    try:
        coroutine.send(None)
    except StopIteration as completed:
        return completed.value
    raise AssertionError("fake transport unexpectedly suspended")


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


class _FakeAdapter:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    async def _request(self, messages, *, output_format=None):
        self.calls.append((messages, output_format))
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    finish_reason="stop",
                    message=SimpleNamespace(
                        content=json.dumps(self.payload, ensure_ascii=False)
                    ),
                )
            ]
        )


class _FailingAdapter:
    async def _request(self, messages, *, output_format=None):
        raise LLMTimeout("local generation timed out")


def test_grounded_enrichment_cannot_change_state_or_terms(snapshot):
    card = snapshot.get_active("body_slim")
    adapter = _FakeAdapter(
        {
            "answer_text": (
                f"슬림 자료로 분류했어요. 그림에서 {card['look_for'][0]}를 확인하세요."
            ),
            "query_choices": [
                {
                    "term_id": "body_slim",
                    "query_fragments": ["slim body reference"],
                }
            ],
        }
    )

    result = _run_immediate(
        OllamaGroundedInterpreter(snapshot, adapter).interpret_grounded(
            "마르고 팔다리가 긴 캐릭터 체형 자료를 찾고 싶어"
        )
    )

    assert isinstance(result, GroundedInterpretationResult)
    assert result.interpretation.interpretation_state.value == "select_terms"
    assert [item.term_id for item in result.interpretation.selections] == ["body_slim"]
    assert result.query_fragments_by_term == {
        "body_slim": ("slim body reference",)
    }
    assert len(adapter.calls) == 1


def test_unapproved_query_fragment_falls_back_to_catalog_queries(snapshot):
    card = snapshot.get_active("body_slim")
    adapter = _FakeAdapter(
        {
            "answer_text": f"슬림 자료이며 {card['look_for'][0]}를 확인하세요.",
            "query_choices": [
                {"term_id": "body_slim", "query_fragments": ["invented search"]}
            ],
        }
    )

    result = _run_immediate(
        OllamaGroundedInterpreter(snapshot, adapter).interpret_grounded(
            "마르고 팔다리가 긴 캐릭터 체형 자료를 찾고 싶어"
        )
    )

    assert result.query_fragments_by_term == {
        "body_slim": tuple(card["query_fragments"])
    }


def test_ungrounded_explanation_falls_back_to_catalog_text(snapshot):
    adapter = _FakeAdapter(
        {
            "answer_text": "This is a useful drawing reference.",
            "query_choices": [],
        }
    )

    result = _run_immediate(
        OllamaGroundedInterpreter(snapshot, adapter).interpret_grounded(
            "마르고 팔다리가 긴 캐릭터 체형 자료를 찾고 싶어"
        )
    )

    assert "슬림" in result.interpretation.answer_text
    assert snapshot.get_active("body_slim")["look_for"][0] in result.interpretation.answer_text
    assert "This is" not in result.interpretation.answer_text


def test_clarification_does_not_call_model(snapshot):
    adapter = _FakeAdapter({"answer_text": "호출되면 안 됨", "query_choices": []})

    result = _run_immediate(
        OllamaGroundedInterpreter(snapshot, adapter).interpret_grounded(
            "그냥 멋지고 자연스러운 자료"
        )
    )

    assert result.interpretation.interpretation_state.value == "needs_clarification"
    assert result.query_fragments_by_term == {}
    assert adapter.calls == []


def test_model_failure_keeps_deterministic_selection_and_catalog_queries(snapshot):
    result = _run_immediate(
        OllamaGroundedInterpreter(snapshot, _FailingAdapter()).interpret_grounded(
            "마르고 팔다리가 긴 캐릭터 체형 자료를 찾고 싶어"
        )
    )

    assert [item.term_id for item in result.interpretation.selections] == ["body_slim"]
    assert result.query_fragments_by_term == {
        "body_slim": tuple(snapshot.get_active("body_slim")["query_fragments"])
    }
