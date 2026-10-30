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
from backend.services.llm import LLMError, _extract_content
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


class _GroundedEnrichment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer_text: str = Field(min_length=1, max_length=1200)
    query_choices: list[_GroundedQueryChoice] = Field(max_length=10)


@dataclass(frozen=True)
class GroundedInterpretationResult:
    interpretation: InterpretationOutput
    query_fragments_by_term: dict[str, tuple[str, ...]]


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
) -> dict[str, tuple[str, ...]]:
    defaults = _default_queries(snapshot, interpretation)
    chosen: dict[str, tuple[str, ...]] = {}
    for choice in enrichment.query_choices:
        allowed = defaults.get(choice.term_id)
        if allowed is None:
            continue
        fragments = tuple(dict.fromkeys(choice.query_fragments))
        if fragments and all(fragment in allowed for fragment in fragments):
            chosen[choice.term_id] = fragments
    return {
        term_id: chosen.get(term_id, fragments)
        for term_id, fragments in defaults.items()
    }


def _is_grounded_answer(
    text: str, snapshot: CatalogSnapshot, interpretation: InterpretationOutput
) -> bool:
    if not _KOREAN_PATTERN.search(text) or _UNSAFE_ANSWER_PATTERN.search(text):
        return False
    selected_ids = {selection.term_id for selection in interpretation.selections}
    if any(term_id in text for term_id in selected_ids):
        return False
    cards = [snapshot.get_active(term_id) for term_id in selected_ids]
    if any(str(card["label_ko"]) not in text for card in cards):
        return False
    checkpoints = [str(item) for card in cards for item in card["look_for"]]
    return any(checkpoint in text for checkpoint in checkpoints)


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
                    "Mention every label_ko and quote at least one look_for checkpoint exactly. "
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
        try:
            response = await self.llm_adapter._request(
                messages, output_format=output_format
            )
            enrichment = _GroundedEnrichment.model_validate_json(
                _extract_content(response)
            )
        except (LLMError, ValidationError, ValueError, TypeError, json.JSONDecodeError):
            return GroundedInterpretationResult(interpretation, defaults)

        answer_text = enrichment.answer_text
        if not _is_grounded_answer(answer_text, self.snapshot, interpretation):
            answer_text = interpretation.answer_text
        enriched = interpretation.model_copy(update={"answer_text": answer_text})
        return GroundedInterpretationResult(
            enriched,
            _validated_queries(self.snapshot, enriched, enrichment),
        )
