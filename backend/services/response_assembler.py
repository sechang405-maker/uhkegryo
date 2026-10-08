"""최종 응답 조립 (api-contract AC-07, term-card-catalog.md 피드백 매핑).

개별 용어 피드백은 JSON에서만 조립하며 LLM이 만들지 않는다.
일반/부분 결과의 통합 answer_text는 검증된 해석에서 별도로 전달한다.
- 피드백 우선: `active_term_feedback[term_id]`가 있으면
  `plain_meaning_ko / selection_reason_template_ko / reference_checkpoints_ko`를 사용한다.
- 폴백: `source_answer_draft -> plain_meaning_ko`, `selection_reason=null`,
  `look_for -> reference_checkpoints`.
- `search_url`은 결정론 URL 빌더가 만든다. `pins`는 provider(T16)의 결과를 역할 사례로 주입받는다.
- 역할 순서(body→pose→view→perspective→layout)와 역할당 최대 1개, 사유 코드 집계는 계약을 따른다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

from backend.schemas.enums import AgentStatus, ReasonCode, Role
from backend.schemas.models import (
    AgentResult,
    PinResult,
    ReferencePlan,
    TermResult,
)
from backend.services.catalog_repository import CatalogSnapshot
from backend.services.resolver import (
    STATUS_CLARIFY,
    STATUS_PROCEED,
    ResolutionResult,
    ValidatedTerm,
)
from backend.services.search_url_builder import build_search_url

SEARCH_REASON_CODES = {
    ReasonCode.PIN_RESULTS_EMPTY,
    ReasonCode.PIN_SEARCH_UNAVAILABLE,
}


@dataclass
class RoleSearchOutcome:
    """provider(T16)가 주입하는 역할 검색 결과 한 건."""

    role: Role
    pins: list[PinResult] = field(default_factory=list)
    code: ReasonCode | None = None  # None=정상(빈 배열), PIN_RESULTS_EMPTY, PIN_SEARCH_UNAVAILABLE


def assemble(
    resolution: ResolutionResult,
    snapshot: CatalogSnapshot,
    search_outcomes: Mapping[Role, RoleSearchOutcome] | None = None,
    *, answer_text: str = "",
) -> AgentResult:
    """resolution과 카탈로그·검색 결과를 조합해 최종 `AgentResult`를 만든다."""
    if resolution.status == STATUS_CLARIFY:
        return AgentResult(
            agent_status=AgentStatus.NEEDS_CLARIFICATION,
            reason_codes=resolution.reason_codes,
            clarifying_question=resolution.clarifying_question,
            reference_plan=None,
        )
    if resolution.status != STATUS_PROCEED:
        raise ValueError(
            f"assemble은 proceed/clarify 결과만 받는다. status={resolution.status}"
        )

    outcomes = search_outcomes or {}
    terms: list[TermResult] = []
    for vt in resolution.terms:
        terms.append(_build_term(vt, snapshot, outcomes.get(vt.selection.role)))

    agent_codes = _aggregate_codes(terms)
    agent_status = (
        AgentStatus.PARTIAL_RESULT if agent_codes else AgentStatus.SUCCESS
    )
    plan = ReferencePlan(terms=terms, unresolved_roles=resolution.unresolved_roles)

    return AgentResult(
        agent_status=agent_status,
        reason_codes=agent_codes,
        reference_plan=plan,
        answer_text=answer_text,
    )


def _build_term(
    vt: ValidatedTerm,
    snapshot: CatalogSnapshot,
    outcome: RoleSearchOutcome | None,
) -> TermResult:
    card = vt.card
    term_id = vt.selection.term_id
    plain_meaning, selection_reason, checkpoints = _feedback_texts(snapshot, term_id, card)

    term_codes: list[ReasonCode] = []

    pins: list[PinResult] = []
    if outcome is not None:
        if outcome.code is not None and outcome.code not in SEARCH_REASON_CODES:
            raise ValueError(f"RoleSearchOutcome.code는 검색 사유 코드만 가능하다: {outcome.code}")
        pins = outcome.pins
        if outcome.code is not None:
            term_codes = [outcome.code]

    return TermResult(
        role=vt.selection.role,
        term_id=term_id,
        label_ko=card["label_ko"],
        label_en=card["label_en"],
        plain_meaning_ko=plain_meaning,
        selection_reason=selection_reason,
        reference_checkpoints=checkpoints,
        search_url=build_search_url(card["query_fragments"]),
        pins=pins,
        reason_codes=term_codes,
    )


def _feedback_texts(
    snapshot: CatalogSnapshot, term_id: str, card: dict
) -> tuple[str, str | None, list[str]]:
    """term-card-catalog.md 피드백 매핑 — 피드백 우선, 없으면 카드 폴백."""
    fb = snapshot.feedback.get(term_id)
    if fb:
        return (
            fb["plain_meaning_ko"],
            fb["selection_reason_template_ko"],
            list(fb["reference_checkpoints_ko"]),
        )
    return card["source_answer_draft"], None, list(card["look_for"])


def _aggregate_codes(terms: list[TermResult]) -> list[ReasonCode]:
    """역할 코드의 중복 없는 전체 집계 (역할 순서대로)."""
    seen: set[ReasonCode] = set()
    aggregated: list[ReasonCode] = []
    for term in terms:
        for code in term.reason_codes:
            if code not in seen:
                seen.add(code)
                aggregated.append(code)
    return aggregated
