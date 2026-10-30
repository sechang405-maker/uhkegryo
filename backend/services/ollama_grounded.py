"""Ollama-only deterministic catalog planning and bounded text enrichment."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from backend.schemas.enums import ClarificationType, InterpretationState, Role
from backend.schemas.models import InterpretationOutput, InterpretationSelection
from backend.services.catalog_repository import CatalogSnapshot
from backend.services.input_safety import normalize_input_text
from backend.services.llm import LLMConfigurationError, LLMError, _extract_content
from backend.services.resolver import clarification_question
from backend.services.structured_output import strict_schema


_GENERIC_WORDS = {
    "그냥", "좋은", "멋진", "멋지고", "자연스러운", "자료", "캐릭터", "인물",
    "자세", "포즈", "구도", "체형", "표현", "묘사", "명시", "경우", "정보",
    "보이는", "보인다", "있다는", "있는", "있음", "있", "한다는", "배경", "원근",
    "화면", "본다는", "본다", "나온다는", "향함", "또는", "해당하는", "해당하",
    "자세의", "하나", "이상의", "단서", "이에", "말고", "reference", "character",
    "pose", "view", "drawing",
}
_SUFFIXES = (
    "이라는", "라는", "한다는", "있다는", "보인다는", "나온다는", "정도", "에서",
    "으로", "처럼", "하고", "있는", "다는", "이다", "한다", "하게", "이며", "이고",
    "이나", "까지", "부터", "에서", "에게", "와", "과", "을", "를", "은", "는",
    "이", "가", "에", "의",
)
_MIN_SCORE = 4.0
_SHORT_SIGNAL_WORDS = {"앉", "눕", "걷", "뛰", "넓", "좁", "손"}
_WORD_STEMS = {
    "마르고": "마르",
    "마른": "마르",
    "길고": "길",
    "긴": "길",
    "길다는": "길",
    "가늘고": "가늘",
    "가늘다는": "가늘",
    "앉아": "앉",
    "앉는": "앉",
    "앉음": "앉",
    "모이는": "모이",
    "모인다": "모이",
    "모임": "모이",
    "모여": "모이",
}
_CONCEPT_PREFIXES = (
    ("호리호리", "마르"),
    ("길쭉", "길"),
    ("무게", "체중"),
    ("발", "다리"),
    ("몰고", "싣"),
    ("싣", "싣"),
    ("골반선", "골반"),
    ("비스듬", "기울"),
    ("걸터앉", "앉"),
    ("하체", "골반"),
    ("넓", "넓"),
    ("좁", "좁"),
    ("발끝", "발"),
    ("발까지", "발"),
)
_TERM_CUE_GROUPS: dict[str, tuple[tuple[str, ...], ...]] = {
    "view_low_angle": (
        (r"아래", r"밑"),
        (r"올려다보", r"치켜보", r"위로\s*보"),
    ),
    "perspective_foreshortening": (
        (r"카메라", r"렌즈"),
        (r"뻗", r"내밀", r"앞으로\s*쭉"),
        (r"팔", r"손", r"발"),
    ),
    "perspective_two_point": (
        (r"두", r"좌우", r"양옆", r"서로\s*다른"),
        (r"소실점",),
    ),
    "pose_support_wall": (
        (r"벽",),
        (r"기대", r"등받이", r"등.{0,8}벽"),
    ),
    "pose_leaping": (
        (r"도약", r"뛰어오", r"점프", r"공중", r"허공"),
    ),
    "pose_a_pose": (
        (r"\bA\s*자",),
        (r"포즈", r"스탠딩", r"팔다리"),
    ),
}
_TERM_CUE_GROUPS["pose_sitting"] = (("\uc549",),)

_POINT_PERSPECTIVE_CUES = {
    "perspective_one_point": r"(?:1|한|일)\s*점\s*(?:투시|원근)",
    "perspective_two_point": r"(?:2|두|이)\s*점\s*(?:투시|원근)",
    "perspective_three_point": r"(?:3|세|삼)\s*점\s*(?:투시|원근)",
}


def _matches_both(text: str, first: str, second: str) -> tuple[str, ...]:
    """Return evidence only when both sides of a visual relation are present."""
    first_match = re.search(first, text, re.IGNORECASE)
    second_match = re.search(second, text, re.IGNORECASE)
    if first_match is None or second_match is None:
        return ()
    return tuple(dict.fromkeys((first_match.group(0), second_match.group(0))))


def _body_shape_direction(text: str) -> str | None:
    """Resolve upper/lower width relations without substring label matching."""
    upper = r"(?:\uc5b4\uae68|\uc0c1\uccb4|\uc717\ubd80\ubd84)"
    lower = r"(?:\uc544\ub798|\uc544\ub7ab\ubd80\ubd84|\uace8\ubc18|\uc5c9\ub369\uc774|\ud558\uccb4)"
    narrow = r"(?:\uc881|\uac00\ub298|\ud3ed\uc774?\s*\uc791)"
    wide = r"(?:\ub113|\uad75|\ud3ed(?:\uc740|\uc774|\uac00)?\s*(?:\ud06c|\ucee4))"
    upper_narrow = re.search(
        rf"{upper}(?:(?!{lower}).){{0,12}}{narrow}|{narrow}.{{0,8}}{upper}", text
    )
    upper_wide = re.search(
        rf"{upper}(?:(?!{lower}).){{0,12}}{wide}|{wide}.{{0,8}}{upper}", text
    )
    lower_narrow = re.search(
        rf"{lower}(?:(?!{upper}).){{0,14}}(?:{narrow}|\uc904\uc5b4)|(?:{narrow}|\uc904\uc5b4).{{0,8}}{lower}",
        text,
    )
    lower_wide = re.search(
        rf"{lower}(?:(?!{upper}).){{0,14}}(?:{wide}|\ud37c\uc9c0)|(?:{wide}|\ud37c\uc9c0).{{0,8}}{lower}",
        text,
    )
    if upper_narrow and lower_wide:
        return "body_triangle"
    if upper_wide and lower_narrow:
        return "body_inverted_triangle"
    return None


def _structural_evidence(term_id: str, text: str) -> tuple[str, ...]:
    normalized = normalize_input_text(text).casefold()
    if term_id == "view_high_angle":
        return _matches_both(
            normalized,
            r"(?:\uc704|\ub192|\uc0c1\uacf5|\uc9c0\ubd95|\uba38\ub9ac.{0,6}\uc704)",
            r"(?:\uc544\ub798|\ubc14\ub2e5|\ub545).{0,10}(?:\ubcf4|\ud5a5|\ub0b4\ub824\ub2e4)|\ub0b4\ub824\ub2e4",
        )
    if term_id == "view_low_angle":
        return _matches_both(
            normalized,
            r"(?:\ubc1c\ubc11|\ubc1c\uce58|(?:\ubc14\ub2e5|\uc544\ub798).{0,8}(?:\ucabd|\uc5d0\uc11c)|\ubb34\ub98e.{0,8}\ub0ae|\uce74\uba54\ub77c.{0,8}\ub0ae)",
            r"(?:\uc704|\uc5bc\uad74|\ud131).{0,10}(?:\ubcf4|\ud5a5)|\uc62c\ub824\ub2e4",
        )
    if term_id == "perspective_two_point":
        return _matches_both(
            normalized,
            r"(?:\ubaa8\uc11c\ub9ac|\uadc0\ud241\uc774|\ucf54\ub108|\uc591\ucabd\s*\ubcbd|\ub450\s*\ubcbd)",
            r"(?:\uc11c\ub85c\s*(?:\ub2e4\ub978|\ubc18\ub300)\s*\ubc29\ud5a5|\uc88c\uc6b0.{0,12}(?:\ub2e4\ub978|\ubc8c\uc5b4|\ud5a5\ud558)|\uc67c\ucabd.{0,24}\uc624\ub978\ucabd.{0,24}\ub2e4\ub978)",
        )
    if term_id == "perspective_foreshortening":
        return _matches_both(
            normalized,
            r"(?:\ub208|\uc5bc\uad74|\ub80c\uc988|\uce74\uba54\ub77c).{0,8}(?:\uc55e|\uac00\uae4c)|\uac00\uae4c\uc6b4",
            r"(?:\uba40\ub9ac|\uba3c|\ub4a4\ucabd|\ub4a4\ud3b8|\ud6c4\ubc29).{0,14}(?:\uc791|\uc881|\uc9e7)",
        )
    direction = _body_shape_direction(normalized)
    if term_id == direction:
        return (normalized[:120],)
    if term_id == "pose_contrapposto":
        return _contrapposto_evidence(normalized)
    return ()


def _contrapposto_evidence(text: str) -> tuple[str, ...]:
    weight_leg = _matches_both(
        text,
        r"(?:(?:\ud55c\ucabd|\uc67c|\uc624\ub978)\s*(?:\ubc1c|\ub2e4\ub9ac))",
        r"(?:\uccb4\uc911|\ubb34\uac8c|\uc911\uc2ec).{0,8}(?:\uc2e3|\ub450|\uac78|\ubab0)",
    )
    counter_tilt = _matches_both(
        text,
        r"\uc5b4\uae68.{0,14}(?:\uae30\uc6b8|\uacbd\uc0ac|\uc0ac\uc120)",
        r"\uace8\ubc18.{0,14}(?:\ubc18\ub300|\uc5ed\ubc29\ud5a5|\uae30\uc6b8|\uacbd\uc0ac|\uc0ac\uc120)",
    )
    return tuple(dict.fromkeys((*weight_leg, *counter_tilt)))


def _requires_stronger_pose_relation(term_id: str, text: str, label: str) -> bool:
    normalized = normalize_input_text(text).casefold()
    if _has_affirmed_phrase(normalized, label.casefold()):
        return False
    if term_id == "pose_contrapposto":
        return not _contrapposto_evidence(normalized)
    if term_id == "pose_hand_open_palm":
        open_palm = _matches_both(
            normalized,
            r"\uc190\ubc14\ub2e5",
            r"(?:\ud3b4|\ubc8c\ub824|\ubcf4\uc5ec|\uc815\uba74)",
        )
        return not open_palm
    if term_id == "pose_supine":
        lying = re.search(
            r"(?:\ubc14\ub2e5|\uce68\ub300|\ub9e4\ud2b8).{0,12}(?:\ub204\uc6cc|\ub208|\ub4f1\uc744\s*\ub300)|(?:\ubc18\ub4ef\uc774|\ucc9c\uc7a5).{0,8}(?:\ub204\uc6cc|\ubcf4)",
            normalized,
        )
        return lying is None
    return False


@dataclass(frozen=True)
class _Candidate:
    term_id: str
    role: Role
    component: str
    score: float
    evidence: tuple[str, ...]


class _GroundedQueryChoice(BaseModel):
    model_config = ConfigDict(extra="forbid")

    term_id: str
    query_fragments: list[str] = Field(max_length=4)


class _GroundedEvidenceChoice(BaseModel):
    model_config = ConfigDict(extra="forbid")

    term_id: str
    look_for: str = Field(min_length=1, max_length=240)


class _GroundedEnrichment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer_text: str = Field(min_length=1, max_length=1200)
    query_choices: list[_GroundedQueryChoice] = Field(max_length=10)
    evidence_choices: list[_GroundedEvidenceChoice] = Field(max_length=10)


@dataclass(frozen=True)
class GroundedInterpretationResult:
    interpretation: InterpretationOutput
    query_fragments_by_term: dict[str, tuple[str, ...]]
    model_called: bool = False
    model_answer_accepted: bool = False
    model_query_applied: bool = False
    model_answer_text: str | None = None
    model_raw_output: str | None = None
    model_answer_rejection_reason: str | None = None
    model_evidence_accepted: bool = False
    model_answer_sanitized: bool = False


_CONFLICTING_TERMS: dict[str, frozenset[str]] = {
    "view_low_angle": frozenset({"view_high_angle"}),
    "view_high_angle": frozenset({"view_low_angle"}),
    "view_front": frozenset({"view_back"}),
    "view_back": frozenset({"view_front"}),
    "perspective_one_point": frozenset({"perspective_two_point", "perspective_three_point"}),
    "perspective_two_point": frozenset({"perspective_one_point", "perspective_three_point"}),
    "perspective_three_point": frozenset({"perspective_one_point", "perspective_two_point"}),
}


def _canonical_word(raw: str) -> str:
    for prefix, canonical in _CONCEPT_PREFIXES:
        if raw.startswith(prefix):
            return canonical
    word = _WORD_STEMS.get(raw, raw)
    for suffix in _SUFFIXES:
        if word.endswith(suffix) and len(word) - len(suffix) >= 2:
            word = word[:-len(suffix)]
            break
    return _WORD_STEMS.get(word, word)


def _token_pairs(text: str, *, reject_negated: bool = False) -> tuple[tuple[str, str], ...]:
    normalized = normalize_input_text(text).casefold()
    words: list[tuple[str, str]] = []
    for match in re.finditer(r"[가-힣]{1,}|[a-z0-9]+", normalized):
        raw = match.group(0)
        if raw in _GENERIC_WORDS:
            continue
        if reject_negated and re.match(
            r".{0,12}(?:말고|아닌|제외|빼고)", normalized[match.end():]
        ):
            continue
        word = _canonical_word(raw)
        if word not in _GENERIC_WORDS and (len(word) >= 2 or word in _SHORT_SIGNAL_WORDS):
            words.append((word, raw))
    return tuple(dict.fromkeys(words))


def _tokens(text: str) -> tuple[str, ...]:
    words = [canonical for canonical, _raw in _token_pairs(text)]
    return tuple(dict.fromkeys(words))


def _token_matches(query: str, signal: str) -> bool:
    if query == signal:
        return True
    return min(len(query), len(signal)) >= 3 and (query in signal or signal in query)


def _score_card(request_text: str, term_id: str, card: dict) -> _Candidate | None:
    if _requires_stronger_pose_relation(
        term_id, request_text, str(card["label_ko"])
    ):
        return None
    request_pairs = _token_pairs(request_text, reject_negated=True)
    request_tokens = tuple(canonical for canonical, _raw in request_pairs)
    label_tokens = _tokens(str(card["label_ko"]))
    evidence: list[str] = []
    score = 0.0

    label_matches = [
        (query, raw) for query, raw in request_pairs
        if any(query == label for label in label_tokens)
    ]
    if label_tokens and len({query for query, _raw in label_matches}) == len(set(label_tokens)):
        score = 12.0 + max(0, len(label_tokens) - 1) * 2.0
        evidence.extend(raw for _query, raw in label_matches)

    for phrase in card.get("confidence_gate", {}).get("require_any", ()):
        signal_tokens = _tokens(str(phrase))
        if not signal_tokens:
            continue
        matches = [
            (query, raw) for query, raw in request_pairs
            if any(_token_matches(query, signal) for signal in signal_tokens)
        ]
        matches = list(dict.fromkeys(matches))
        if not matches:
            continue
        coverage = len({query for query, _raw in matches}) / len(signal_tokens)
        if coverage < 0.6:
            continue
        phrase_score = len(matches) * 4.0
        if coverage >= 0.75:
            phrase_score += 4.0
        if phrase_score > score:
            score = phrase_score
        evidence.extend(raw for _query, raw in matches)

    point_cue = _POINT_PERSPECTIVE_CUES.get(term_id)
    if point_cue and (match := re.search(point_cue, request_text, re.IGNORECASE)):
        score = max(score, 16.0)
        evidence.append(match.group(0))

    structural_evidence = _structural_evidence(term_id, request_text)
    if structural_evidence:
        score = max(score, 18.0)
        evidence.extend(structural_evidence)

    cue_groups = _TERM_CUE_GROUPS.get(term_id)
    if cue_groups:
        cue_evidence: list[str] = []
        for alternatives in cue_groups:
            match = next(
                (
                    re.search(pattern, request_text, re.IGNORECASE)
                    for pattern in alternatives
                    if re.search(pattern, request_text, re.IGNORECASE)
                ),
                None,
            )
            if match is None:
                cue_evidence = []
                break
            cue_evidence.append(match.group(0))
        if cue_evidence:
            score = max(score, 10.0 + len(cue_evidence))
            evidence.extend(cue_evidence)

    evidence = list(dict.fromkeys(evidence))
    if score < _MIN_SCORE or not evidence:
        return None
    return _Candidate(
        term_id=term_id,
        role=Role(card["role"]),
        component=str(card.get("component", "primary")),
        score=score,
        evidence=tuple(evidence[:3]),
    )


def _contradicted(term_id: str, request_text: str) -> bool:
    text = normalize_input_text(request_text).casefold()
    negated_labels = {
        "view_high_angle": r"\ud558\uc774\s*\uc575\uae00(?:\uc740|\ub294|\uc744|\ub97c)?\s*(?:\uc544\ub2c8|\uc81c\uc678|\ube7c|\ub9d0\uace0)",
        "view_low_angle": r"\ub85c\uc6b0\s*\uc575\uae00(?:\uc740|\ub294|\uc744|\ub97c)?\s*(?:\uc544\ub2c8|\uc81c\uc678|\ube7c|\ub9d0\uace0)",
    }
    if term_id in negated_labels and re.search(negated_labels[term_id], text):
        return True
    body_direction = _body_shape_direction(text)
    if term_id in {"body_triangle", "body_inverted_triangle"}:
        if body_direction is not None and body_direction != term_id:
            return True
    if term_id == "body_triangle" and "역삼각형" in text:
        return True
    if term_id == "body_hourglass" and re.search(
        r"어깨.{0,12}넓.{0,20}(?:골반|하체).{0,12}좁", text
    ):
        return True
    if term_id in {"perspective_two_point", "perspective_three_point"} and re.search(
        r"(?:한|1)\s*(?:점|개의?\s*소실점)|한\s*점으로", text
    ):
        return True
    if term_id in {"perspective_one_point", "perspective_three_point"} and re.search(
        r"(?:두|2)\s*(?:점|개의?\s*소실점)", text
    ):
        return True
    if term_id in {"perspective_one_point", "perspective_two_point"} and re.search(
        r"(?:세|3)\s*(?:점|개의?\s*소실점)", text
    ):
        return True
    return False


def _select_candidates(request_text: str, snapshot: CatalogSnapshot) -> list[_Candidate]:
    ranked = sorted(
        (
            candidate
            for term_id, card in snapshot.active_cards.items()
            if card.get("component") != "composite"
            if not _contradicted(term_id, request_text)
            if (candidate := _score_card(request_text, term_id, card)) is not None
        ),
        key=lambda candidate: (-candidate.score, list(Role).index(candidate.role), candidate.term_id),
    )
    selected: list[_Candidate] = []
    evidence_by_role: dict[Role, set[str]] = {}
    components_by_role: dict[Role, set[str]] = {}
    for candidate in ranked:
        role_evidence = evidence_by_role.setdefault(candidate.role, set())
        role_components = components_by_role.setdefault(candidate.role, set())
        same_role = [item for item in selected if item.role is candidate.role]
        if same_role:
            top = same_role[0]
            distinct = set(candidate.evidence) - role_evidence
            different_component = candidate.component not in role_components
            if candidate.score < top.score * 0.5 or (not distinct and not different_component):
                continue
        selected.append(candidate)
        role_evidence.update(candidate.evidence)
        role_components.add(candidate.component)

    text = normalize_input_text(request_text)
    selected_ids = {item.term_id for item in selected}
    convergence = re.search(
        r"(?:한\s*점|점으로|소실점).*(?:모이|수렴)|(?:모이|수렴).*(?:한\s*점|점으로|소실점)",
        text,
    )
    if (
        "perspective_vanishing_point" in selected_ids
        and "perspective_one_point" not in selected_ids
        and convergence
    ):
        card = snapshot.get_active("perspective_one_point")
        selected.append(_Candidate(
            term_id="perspective_one_point",
            role=Role(card["role"]),
            component=str(card.get("component", "primary")),
            score=_MIN_SCORE,
            evidence=("한 점" if "한 점" in text else "점으로",),
        ))
        selected_ids.add("perspective_one_point")
    if (
        "perspective_one_point" in selected_ids
        and "perspective_vanishing_point" not in selected_ids
        and convergence
    ):
        card = snapshot.get_active("perspective_vanishing_point")
        selected.append(_Candidate(
            term_id="perspective_vanishing_point",
            role=Role(card["role"]),
            component=str(card.get("component", "primary")),
            score=_MIN_SCORE,
            evidence=("한 점" if "한 점" in text else "소실점",),
        ))

    order = {role: index for index, role in enumerate(snapshot.roles_order or tuple(Role))}
    return sorted(selected[:10], key=lambda item: (order[item.role], -item.score, item.term_id))


def _is_conflicting_request(request_text: str) -> bool:
    text = normalize_input_text(request_text)
    front = bool(re.search(r"(?:완전한\s*)?(?:정면|앞모습)", text))
    back = bool(re.search(r"(?:완전한\s*)?(?:뒷모습|후면)", text))
    simultaneous = any(word in text for word in ("동시에", "이면서", "하면서"))
    return front and back and simultaneous


def _fallback_answer(snapshot: CatalogSnapshot, candidates: list[_Candidate]) -> str:
    clauses: list[str] = []
    checkpoints: list[str] = []
    for candidate in candidates:
        card = snapshot.get_active(candidate.term_id)
        clauses.append(f"**{card['label_ko']}**")
        checkpoints.append(str(card["look_for"][0]))
    labels = ", ".join(clauses)
    return (
        f"요청의 구체적인 단서를 기준으로 {labels} 자료를 찾을 수 있어요. "
        f"그릴 때는 {'; '.join(checkpoints)}을 확인해 보세요."
    )


def _clarification(request_text: str, kind: ClarificationType) -> InterpretationOutput:
    return InterpretationOutput(
        interpretation_state=InterpretationState.NEEDS_CLARIFICATION,
        unresolved_constraints=[normalize_input_text(request_text)],
        clarifying_question=clarification_question(kind, request_text),
        clarification_type=kind,
    )


def plan_grounded_request(
    request_text: str, snapshot: CatalogSnapshot
) -> InterpretationOutput:
    """Build state and catalog selections without model-generated IDs or state fields."""
    if _is_conflicting_request(request_text):
        return _clarification(request_text, ClarificationType.CONFLICTING_CONSTRAINTS)

    candidates = _select_candidates(request_text, snapshot)
    if not candidates:
        return _clarification(request_text, ClarificationType.INSUFFICIENT_VISUAL_EVIDENCE)

    selections = [
        InterpretationSelection(
            role=candidate.role,
            term_id=candidate.term_id,
            evidence=list(candidate.evidence),
            confidence=min(0.99, 0.5 + candidate.score / 40),
        )
        for candidate in candidates
    ]
    return InterpretationOutput(
        interpretation_state=InterpretationState.SELECT_TERMS,
        selections=selections,
        answer_text=_fallback_answer(snapshot, candidates),
    )


_KOREAN_PATTERN = re.compile(r"[가-힣]")
_UNSAFE_ANSWER_PATTERN = re.compile(
    r"(?:https?://|www\.|<[^>]+>|\[[^\]]+\]\([^)]+\))", re.IGNORECASE
)


def _default_queries(
    snapshot: CatalogSnapshot, interpretation: InterpretationOutput
) -> dict[str, tuple[str, ...]]:
    return {
        selection.term_id: tuple(
            str(fragment)
            for fragment in snapshot.get_active(selection.term_id)["query_fragments"]
        )
        for selection in interpretation.selections
    }


def _validated_queries(
    snapshot: CatalogSnapshot,
    interpretation: InterpretationOutput,
    enrichment: _GroundedEnrichment,
) -> tuple[dict[str, tuple[str, ...]], bool]:
    defaults = _default_queries(snapshot, interpretation)
    chosen: dict[str, tuple[str, ...]] = {}
    for choice in enrichment.query_choices:
        allowed = defaults.get(choice.term_id)
        if allowed is None:
            continue
        fragments = tuple(dict.fromkeys(choice.query_fragments))
        if fragments and all(fragment in allowed for fragment in fragments):
            chosen[choice.term_id] = fragments
    validated = {
        term_id: chosen.get(term_id, fragments)
        for term_id, fragments in defaults.items()
    }
    return validated, any(validated[key] != defaults[key] for key in defaults)


def _answer_rejection_reason(
    text: str,
    snapshot: CatalogSnapshot,
    interpretation: InterpretationOutput,
) -> str | None:
    if not _KOREAN_PATTERN.search(text) or _UNSAFE_ANSWER_PATTERN.search(text):
        return "unsafe_or_non_korean"
    selected_ids = {selection.term_id for selection in interpretation.selections}
    if any(term_id in text for term_id in snapshot.active_cards):
        return "internal_id_leak"
    cards = [snapshot.get_active(term_id) for term_id in selected_ids]
    if any(
        str(fragment).casefold() in text.casefold()
        for card in cards
        for fragment in card["query_fragments"]
    ):
        return "search_fragment_leak"
    if any(str(card["label_ko"]) not in text for card in cards):
        return "missing_catalog_label"
    conflicting_ids = set().union(
        *(_CONFLICTING_TERMS.get(term_id, frozenset()) for term_id in selected_ids)
    )
    for term_id in conflicting_ids:
        label = str(snapshot.get_active(term_id)["label_ko"])
        if _has_affirmed_phrase(text, label):
            return "conflicting_catalog_label"
    return None


def _has_affirmed_phrase(text: str, phrase: str) -> bool:
    for match in re.finditer(re.escape(phrase), text, re.IGNORECASE):
        before = text[max(0, match.start() - 12):match.start()]
        after = text[match.end():match.end() + 12]
        if re.search(
            r"^(?:\uc740|\ub294|\uc774|\uac00|\uc744|\ub97c|\uc5d0\uc11c|\uc73c\ub85c)?\s*"
            r"(?:\ub9d0\uace0|\uc544\ub2cc|\uc81c\uc678|\ube7c\uace0|\uc544\ub2c8)",
            after,
        ):
            continue
        if re.search(r"(?:not|except|exclude)\s*$", before, re.IGNORECASE):
            continue
        return True
    return False


def _sanitize_internal_ids(
    text: str, selected_ids: set[str]
) -> tuple[str, bool]:
    sanitized = text
    for term_id in selected_ids:
        sanitized = re.sub(
            rf"\s*[\(\[]?\s*{re.escape(term_id)}\s*[\)\]]?",
            "",
            sanitized,
            flags=re.IGNORECASE,
        )
    return sanitized.strip(), sanitized != text


def _catalog_evidence_is_valid(
    enrichment: _GroundedEnrichment,
    snapshot: CatalogSnapshot,
    interpretation: InterpretationOutput,
) -> bool:
    selected_ids = {selection.term_id for selection in interpretation.selections}
    evidence_ids = {choice.term_id for choice in enrichment.evidence_choices}
    return evidence_ids == selected_ids and all(
        choice.look_for in snapshot.get_active(choice.term_id)["look_for"]
        for choice in enrichment.evidence_choices
    )


class OllamaGroundedInterpreter:
    """Enrich deterministic Ollama selections without delegating IDs or state."""

    def __init__(self, snapshot: CatalogSnapshot, llm_adapter: Any) -> None:
        self.snapshot = snapshot
        self.llm_adapter = llm_adapter

    async def interpret_grounded(
        self, request_text: str, **_trace_context: Any
    ) -> GroundedInterpretationResult:
        interpretation = plan_grounded_request(request_text, self.snapshot)
        if interpretation.interpretation_state is not InterpretationState.SELECT_TERMS:
            return GroundedInterpretationResult(interpretation, {})

        defaults = _default_queries(self.snapshot, interpretation)
        approved_cards = [
            {
                "term_id": selection.term_id,
                "label_ko": self.snapshot.get_active(selection.term_id)["label_ko"],
                "look_for": self.snapshot.get_active(selection.term_id)["look_for"],
                "query_fragments": defaults[selection.term_id],
            }
            for selection in interpretation.selections
        ]
        messages = [
            {
                "role": "system",
                "content": (
                    "Return only JSON. Explain the approved drawing cards in Korean. "
                    "Mention every label_ko. For every approved card, copy exactly one supplied "
                    "look_for checkpoint into evidence_choices; answer_text may explain it naturally. "
                    "For each term_id, choose only exact query_fragments supplied for that card. "
                    "Never add cards, URLs, HTML, markdown links, or internal IDs to answer_text."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {"request_text": request_text, "approved_cards": approved_cards},
                    ensure_ascii=False,
                ),
            },
        ]
        output_format = {
            "type": "json_schema",
            "json_schema": {
                "name": "grounded_ollama_enrichment",
                "strict": True,
                "schema": strict_schema(_GroundedEnrichment.model_json_schema()),
            },
        }
        raw_content: str | None = None
        try:
            response = await self.llm_adapter._request(
                messages, output_format=output_format
            )
            raw_content = _extract_content(response)
            enrichment = _GroundedEnrichment.model_validate_json(raw_content)
        except LLMConfigurationError:
            raise
        except (LLMError, ValidationError, ValueError, TypeError, json.JSONDecodeError):
            return GroundedInterpretationResult(
                interpretation,
                defaults,
                model_called=True,
                model_answer_text=raw_content,
                model_raw_output=raw_content,
                model_answer_rejection_reason="invalid_structured_output",
            )

        model_answer_text = enrichment.answer_text
        selected_ids = {selection.term_id for selection in interpretation.selections}
        safe_answer_text, answer_sanitized = _sanitize_internal_ids(
            model_answer_text, selected_ids
        )
        rejection_reason = _answer_rejection_reason(
            safe_answer_text,
            self.snapshot,
            interpretation,
        )
        answer_accepted = rejection_reason is None
        evidence_accepted = _catalog_evidence_is_valid(
            enrichment, self.snapshot, interpretation
        )
        answer_text = f"{safe_answer_text}\n\n{interpretation.answer_text}"
        if not answer_accepted:
            answer_text = interpretation.answer_text
        enriched = interpretation.model_copy(update={"answer_text": answer_text})
        queries, query_applied = _validated_queries(
            self.snapshot, enriched, enrichment
        )
        return GroundedInterpretationResult(
            enriched,
            queries,
            model_called=True,
            model_answer_accepted=answer_accepted,
            model_query_applied=query_applied,
            model_answer_text=model_answer_text,
            model_raw_output=raw_content,
            model_answer_rejection_reason=rejection_reason,
            model_evidence_accepted=evidence_accepted,
            model_answer_sanitized=answer_sanitized,
        )
