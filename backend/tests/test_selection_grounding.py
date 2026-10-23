"""Bounded evidence checks, not a general semantic equivalence evaluator."""
import asyncio
from unittest.mock import AsyncMock

import pytest

from backend.schemas.models import InterpretationOutput, InterpretationSelection
from backend.services.conversation_context import validate
from backend.services.llm import LLMInvalidStructuredOutput
from backend.services.resolver import resolve, STATUS_ALL_INVALID, STATUS_PROCEED


def output(term_id="pose_standing", evidence="standing pose", **extra):
    return InterpretationOutput(interpretation_state="select_terms",
        answer_text="서 있는 자세를 참고해 보세요.", selections=[{
            "role": "pose", "term_id": term_id, "evidence": [evidence], "confidence": .9, **extra}])


@pytest.fixture
def catalog(snapshot_factory, card_factory):
    return snapshot_factory([
        card_factory("pose_standing", label_ko="스탠딩", label_en="standing pose"),
        card_factory("pose_sitting", label_ko="시팅", label_en="seated pose"),
        card_factory("view_front", role="view", label_ko="프런트 뷰", label_en="front view"),
        card_factory("pose_action", label_ko="액션 포즈", label_en="action pose"),
        card_factory("pose_gesture", label_ko="동세/액션 라인", label_en="gesture drawing"),
        card_factory("pose_running", label_ko="달리기", label_en="running pose"),
    ], dsd=("pose_action",))


def test_different_card_label_is_not_evidence_for_selected_card(catalog):
    result = resolve(output("pose_sitting"), catalog, request_text="standing pose")
    assert result.status == STATUS_ALL_INVALID


@pytest.mark.parametrize("request_text,evidence", [
    ("standing pose 말고 seated pose", "standing pose"),
    ("스탠딩이 아닌 시팅", "스탠딩"),
    ("not standing pose, seated pose", "standing pose"),
    ("without standing pose", "standing pose"),
    ("standing pose인지 모르겠어", "standing pose"),
    ("maybe standing pose", "standing pose"),
    ("standing pose 제외하지만 front view는 유지해", "standing pose"),
    ("standing pose 빼고 싶지만 front view는 유지해", "standing pose"),
])
def test_excluded_or_uncertain_evidence_is_rejected(catalog, request_text, evidence):
    assert resolve(output(evidence=evidence), catalog, request_text=request_text).status == STATUS_ALL_INVALID


@pytest.mark.parametrize("request_text,evidence", [
    ("standing pose 말고 seated pose", "seated pose"),
    ("not standing pose, seated pose", "seated pose"),
    ("seated pose뿐 아니라 손도 보여줘", "seated pose"),
    ("not only seated pose but also front view", "seated pose"),
    ("의자에 편하게 앉아 있는 모습", "의자에 편하게 앉아"),
    ("seated pose 말고도 손을 보여줘", "seated pose"),
    ("seated pose 제외하지 마", "seated pose"),
    ("seated pose 빼고 싶지 않아", "seated pose"),
])
def test_affirmative_and_natural_language_evidence_is_preserved(catalog, request_text, evidence):
    assert resolve(output("pose_sitting", evidence), catalog, request_text=request_text).status == STATUS_PROCEED


def test_verified_previous_card_label_remains_usable(catalog):
    source = "00000000-0000-0000-0000-000000000001"
    memory = AsyncMock()
    memory.records.return_value = [{"job_id": source, "request_text": "서 있는 사람",
        "terms": [{"label_ko": "스탠딩", "label_en": "standing pose"}]}]
    result = asyncio.run(validate(memory, {"request_text": "아까 자세 유지해줘"},
        output(source_job_id=source), catalog))
    assert result.status == STATUS_PROCEED


def test_filtered_card_cannot_keep_its_original_integrated_answer(catalog):
    interpretation = output("pose_action", "action pose")
    interpretation.selections.append(InterpretationSelection(role="view", term_id="view_front",
        evidence=["front view"], confidence=.9))
    with pytest.raises(LLMInvalidStructuredOutput) as exc:
        asyncio.run(validate(None, {"request_text": "action pose and front view"}, interpretation, catalog))
    assert exc.value.feedback[0]["code"] == "selection_card_invalid"


def test_english_evidence_must_not_be_part_of_an_unrelated_word(catalog):
    assert resolve(output(evidence="standing"), catalog, request_text="understanding composition").status == STATUS_ALL_INVALID


@pytest.mark.parametrize("term_id", ["pose_gesture", "pose_action"])
def test_named_activity_is_not_silently_replaced_with_a_generic_motion_card(catalog, term_id):
    result = resolve(
        output(term_id, "발레를 하는 동작"),
        catalog,
        request_text="발레를 하는 동작을 추가할래",
    )
    assert result.status == STATUS_ALL_INVALID


def test_explicit_motion_technique_and_supported_activity_remain_selectable(catalog):
    technique = resolve(
        output("pose_gesture", "동세/액션 라인"),
        catalog,
        request_text="발레 동작의 동세/액션 라인을 찾고 싶어",
    )
    supported = resolve(
        output("pose_running", "달리기를 하는 동작"),
        catalog,
        request_text="달리기를 하는 동작을 추가할래",
    )
    assert technique.status == STATUS_PROCEED
    assert supported.status == STATUS_PROCEED


def test_descriptive_support_and_parent_card_names_are_not_exact_label_conflicts(catalog, card_factory):
    catalog.active_cards["pose_weight_shift"] = card_factory("pose_weight_shift",
        label_ko="체중 이동", label_en="weight shift", requires_all_of=["pose_standing"])
    assert resolve(output("pose_weight_shift"), catalog, request_text="standing pose").status == STATUS_PROCEED
    interpretation = output("pose_sitting")
    interpretation.selections[0].evidence.append("의자에 앉아")
    assert resolve(interpretation, catalog, request_text="standing pose 대신 의자에 앉아").status == STATUS_PROCEED
