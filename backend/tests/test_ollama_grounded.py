from pathlib import Path
import json
from types import SimpleNamespace

import pytest

from backend.services.catalog_repository import load_catalog
from backend.services.llm import LLMTimeout
from backend.services.ollama_grounded import (
    GroundedInterpretationResult,
    OllamaGroundedInterpreter,
    _answer_rejection_reason,
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
        ("아래에서 올려다보는 로우 앵글 2점 투시로 건물을 그리고 싶어.", {"view_low_angle", "perspective_two_point"}),
        ("정면에서 머리부터 발끝까지 보이는 캐릭터 자료", {"view_front", "view_full_body"}),
        ("어깨는 넓고 허리와 하체는 좁은 역삼각형 체형", {"body_inverted_triangle"}),
        ("복도 끝 한 점으로 선이 모이는 배경 원근", {"perspective_one_point", "perspective_vanishing_point"}),
        ("캐릭터를 아래에서 올려다보는 구도", {"view_low_angle"}),
        ("카메라 쪽으로 뻗은 팔이 크게 보이는 원근 자세", {"perspective_foreshortening"}),
        ("건물 모서리를 중심으로 좌우 두 소실점이 있는 원근", {"perspective_two_point"}),
        ("벽에 등을 기대고 편하게 서 있는 포즈 자료", {"pose_support_wall"}),
        ("달리다가 공중으로 크게 도약하는 역동적인 인물", {"pose_leaping"}),
        ("정면 전신 A자 기본 포즈 시트", {"view_front", "view_full_body", "pose_a_pose"}),
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
        ("좀 더 역동적으로 해줘.", "insufficient_visual_evidence"),
        ("서 있는 자세", "insufficient_visual_evidence"),
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
        ("밑에서 위로 치켜보는 시점", {"view_low_angle"}),
        ("팔을 렌즈 앞으로 쭉 내민 과장된 자세", {"perspective_foreshortening"}),
        ("건물 귀퉁이 양옆의 서로 다른 소실점", {"perspective_two_point"}),
        ("벽을 등받이 삼아 서 있는 모습", {"pose_support_wall"}),
        ("바닥을 차고 허공에 뛰어오른 순간", {"pose_leaping"}),
        ("팔다리를 살짝 벌린 A자 스탠딩", {"pose_a_pose"}),
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
            "evidence_choices": [
                {"term_id": "body_slim", "look_for": card["look_for"][0]}
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
    assert result.model_called is True
    assert result.model_answer_accepted is True
    assert result.model_query_applied is False
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


def test_explanation_that_leaks_search_fragment_uses_catalog_fallback(snapshot):
    card = snapshot.get_active("body_slim")
    adapter = _FakeAdapter({
        "answer_text": (
            f"슬림은 {card['look_for'][0]}를 봅니다. slim body reference로 검색하세요."
        ),
        "query_choices": [],
    })

    result = _run_immediate(
        OllamaGroundedInterpreter(snapshot, adapter).interpret_grounded(
            "마르고 팔다리가 긴 캐릭터 체형 자료를 찾고 싶어"
        )
    )

    assert "slim body reference" not in result.interpretation.answer_text
    assert result.model_answer_accepted is False


def test_clarification_does_not_call_model(snapshot):
    adapter = _FakeAdapter({"answer_text": "호출되면 안 됨", "query_choices": []})

    result = _run_immediate(
        OllamaGroundedInterpreter(snapshot, adapter).interpret_grounded(
            "그냥 멋지고 자연스러운 자료"
        )
    )

    assert result.interpretation.interpretation_state.value == "needs_clarification"
    assert result.query_fragments_by_term == {}
    assert result.model_called is False
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
    assert result.model_called is True
    assert result.model_answer_accepted is False


def test_answer_validator_accepts_a_paraphrase_with_explicit_catalog_evidence(snapshot):
    card = snapshot.get_active("body_slim")
    interpretation = plan_grounded_request(
        card["confidence_gate"]["require_any"][0], snapshot
    )
    text = f"{card['label_ko']}: \uc120\ud0dd\ud55c \uccb4\ud615\uc744 \uadf8\ub9b4 \ub54c \uc804\uccb4 \ube44\uc728\uc744 \uc0b4\ud3b4\ubcf4\uc138\uc694."

    reason = _answer_rejection_reason(
        text,
        snapshot,
        interpretation,
    )

    assert reason is None
    assert card["look_for"][0] not in text


def test_catalog_evidence_copy_is_diagnostic_not_an_answer_rejection(snapshot):
    card = snapshot.get_active("body_slim")
    interpretation = plan_grounded_request(
        card["confidence_gate"]["require_any"][0], snapshot
    )
    text = f"{card['label_ko']}: \uc804\uccb4 \ube44\uc728\uc744 \uc0b4\ud3b4\ubcf4\uc138\uc694."

    assert _answer_rejection_reason(text, snapshot, interpretation) is None

    adapter = _FakeAdapter({
        "answer_text": text,
        "query_choices": [],
        "evidence_choices": [
            {"term_id": "body_slim", "look_for": "invented checkpoint"}
        ],
    })
    result = _run_immediate(
        OllamaGroundedInterpreter(snapshot, adapter).interpret_grounded(
            card["confidence_gate"]["require_any"][0]
        )
    )
    assert result.model_answer_accepted is True
    assert result.model_evidence_accepted is False
    assert card["look_for"][0] in result.interpretation.answer_text
