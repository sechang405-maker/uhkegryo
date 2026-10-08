"""결정론 해석 resolver (trust-boundary AC-01, term-card-catalog AC-03·AC-04).

LLM `InterpretationOutput`은 후보일 뿐이며, resolver가 활성 JSON 카탈로그·안전 규칙과
대조한 뒤 최종 응답을 조립하는 데 필요한 근거를 만든다 (api-contract §How).

결정론 검증:
- 활성 메모리 카탈로그에 존재하는지
- 카드 role과 선택 role이 일치하는지
- 활성 카드 query_fragments가 비어 있지 않은지
- 직접 검색 금지(direct_search_disabled) 카드는 URL·provider 호출 금지
- 역할당 최대 1개 후보로 충족(collapse: confidence 최대, 동률은 선발 우선)

`interpretation_state`는 스키마가 `select_terms`/`needs_clarification`으로 강제하며,
needs_clarification일 때는 `clarification_type`을 `ReasonCode`와 서버 고정 질문으로 직접 매핑해
최종 `agent_status`·사유 코드·질문을 만든다 (LLM은 reason_codes나 사용자용 질문을 만들지 않는다).
SKILL.md 판단 기준의 `confidence_gate`·`requires_all_of`·`requires_any_of` 의미 충족은
LLM 판단 몫이며 이 모듈은 재판정하지 않는다. 참조 ID의 구조 무결성은 시작 검증에서 방어한다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from collections.abc import Mapping, Sequence

from backend.schemas.enums import ClarificationType, InterpretationState, ReasonCode, Role
from backend.schemas.models import InterpretationOutput, InterpretationSelection
from backend.services.catalog_repository import CatalogSnapshot
from backend.services.input_safety import normalize_input_text

STATUS_PROCEED = "proceed"
STATUS_CLARIFY = "clarify"
STATUS_ALL_INVALID = "all_invalid"

_CLARIFICATION_TO_REASON: dict[ClarificationType, ReasonCode] = {
    ClarificationType.ABSTRACT_INTENT: ReasonCode.ABSTRACT_INTENT_ONLY,
    ClarificationType.INSUFFICIENT_VISUAL_EVIDENCE: ReasonCode.INSUFFICIENT_VISUAL_EVIDENCE,
    ClarificationType.CONFLICTING_CONSTRAINTS: ReasonCode.CONFLICTING_CONSTRAINTS,
}

_DEFAULT_DSD_QUESTION = (
    "검색하기 어려운 표현이에요. 체형·자세·시점 중 하나를 구체적으로 알려주세요."
)
_CLARIFICATION_QUESTIONS: dict[ClarificationType, str] = {
    ClarificationType.ABSTRACT_INTENT: (
        "원하는 캐릭터의 체형·포즈·시점 중 하나를 구체적으로 설명해 주세요."
    ),
    ClarificationType.INSUFFICIENT_VISUAL_EVIDENCE: (
        "캐릭터의 체형·포즈·시점 중 어떤 정보를 더 알려주실 수 있나요?"
    ),
    ClarificationType.CONFLICTING_CONSTRAINTS: (
        "서로 다른 조건 중 어떤 조건을 우선할지 알려주세요."
    ),
}


def clarification_question(kind: ClarificationType, request_text: str) -> str:
    """Select fixed visual questions without model text or interpolated user data."""
    text = normalize_input_text(request_text)
    if kind is ClarificationType.INSUFFICIENT_VISUAL_EVIDENCE:
        if "어깨" in text and any(word in text for word in ("소매", "망토", "패딩", "의상", "옷")):
            return "의상을 제외한 실제 체형 비율인가요, 의상을 포함한 겉실루엣인가요?"
        if any(word in text for word in ("휘", "곡선", "멋", "자연")) and any(word in text for word in ("서 있", "서있", "선 포즈", "스탠딩")):
            return "한쪽 다리에 체중이 실렸나요, 아니면 허리와 몸통이 S자로 이어지나요?"
    if kind is ClarificationType.CONFLICTING_CONSTRAINTS:
        equal_width = re.search(r"어깨(?:와|랑|·)\s*골반(?:은|이|의)?\s*(?:폭(?:은|이)?\s*)?(?:비슷|같|동일)", text)
        wider_shoulders = re.search(r"어깨(?:가|는)?\s*골반보다\s*(?:(?:훨씬|더)\s*)*넓(?:은|고|다|어|습니다)", text)
        body_conflict = bool(equal_width and wider_shoulders) and not re.search(
            r"(?:비슷하지|같지|동일하지|넓지)\s*(?:않|못)|아니|원하지", text)
        view_conflict = bool(re.search(
            r"옆모습(?:\s*실루엣)?(?:인데|이면서|으로\s*그리고\s*싶은데)[^.?!]*정면처럼", text))
        if body_conflict and not view_conflict:
            return "어깨와 골반 폭이 비슷한 비율과 어깨가 더 넓은 실루엣 중 무엇을 우선할까요?"
        if view_conflict and not body_conflict:
            return "옆모습 실루엣과 정면의 좌우 대칭 중 무엇을 우선할까요?"
    return _CLARIFICATION_QUESTIONS[kind]


@dataclass
class ValidatedTerm:
    """구조 검증을 통과한 역할 후보 한 건."""

    selection: InterpretationSelection
    card: dict
    direct_search_disabled: bool = False


@dataclass
class ResolutionResult:
    """resolver 판정 결과. 조정 계층(T14/T17c)이 상태·재시도·조립 여부를 정한다."""

    status: str
    terms: list[ValidatedTerm] = field(default_factory=list)
    unresolved_roles: list[Role] = field(default_factory=list)
    invalid_candidates: list[InterpretationSelection] = field(default_factory=list)
    reason_codes: list[ReasonCode] = field(default_factory=list)
    clarifying_question: str | None = None


def resolve(
    interpretation: InterpretationOutput, snapshot: CatalogSnapshot, *, request_text: str,
    verified_source_texts: Mapping[str, Sequence[str]] | None = None,
) -> ResolutionResult:
    """LLM 해석 후보를 카탈로그와 대조해 결정론 검증하고 조정 계층에 넘길 결과를 만든다."""
    if interpretation.interpretation_state is InterpretationState.NEEDS_CLARIFICATION:
        code = _CLARIFICATION_TO_REASON.get(interpretation.clarification_type)
        return ResolutionResult(
            status=STATUS_CLARIFY,
            reason_codes=[code or ReasonCode.INSUFFICIENT_VISUAL_EVIDENCE],
            clarifying_question=clarification_question(interpretation.clarification_type, request_text),
        )

    normalized_request = normalize_input_text(request_text)
    valid: list[ValidatedTerm] = []
    direct_disabled: list[ValidatedTerm] = []
    invalid: list[InterpretationSelection] = []

    for selection in interpretation.selections:
        sources = [normalized_request] if selection.source_job_id is None else [
            normalize_input_text(text) for text in
            (verified_source_texts or {}).get(str(selection.source_job_id), ())
        ]
        if not _has_source_evidence(selection, sources):
            invalid.append(selection)
            continue
        card = snapshot.get_active(selection.term_id)
        if card is None or str(card.get("role")) != str(selection.role):
            invalid.append(selection)
            continue
        if not card.get("query_fragments"):
            invalid.append(selection)
            continue
        if snapshot.is_direct_search_disabled(selection.term_id):
            direct_disabled.append(
                ValidatedTerm(selection=selection, card=card, direct_search_disabled=True)
            )
            continue
        valid.append(ValidatedTerm(selection=selection, card=card))

    by_role = collapse_by_role(valid)
    roles_order = snapshot.roles_order or tuple(Role)
    terms = [by_role[role] for role in roles_order if role in by_role]
    unresolved = [role for role in roles_order if role not in by_role]

    if not terms:
        if direct_disabled:
            # term-card-catalog AC-04: URL·provider 호출 없이 질문 하나
            return ResolutionResult(
                status=STATUS_CLARIFY,
                invalid_candidates=invalid,
                reason_codes=[ReasonCode.DIRECT_SEARCH_DISABLED],
                clarifying_question=interpretation.clarifying_question or _DEFAULT_DSD_QUESTION,
            )
        # 후보가 전부 비활성·역할 불일치 → 조정 계층은 LLM 재시도를 검토
        return ResolutionResult(status=STATUS_ALL_INVALID, invalid_candidates=invalid)

    return ResolutionResult(
        status=STATUS_PROCEED,
        terms=terms,
        unresolved_roles=unresolved,
        invalid_candidates=invalid,
    )


def _has_source_evidence(selection: InterpretationSelection, normalized_sources: Sequence[str]) -> bool:
    return all(
        (normalized_evidence := normalize_input_text(evidence))
        and any(normalized_evidence in source for source in normalized_sources)
        for evidence in selection.evidence
    )


def collapse_by_role(valid: list[ValidatedTerm]) -> dict[Role, ValidatedTerm]:
    """역할당 최대 1개 — confidence 최대, 동률이면 선발(입력 순서) 우선."""
    by_role: dict[Role, ValidatedTerm] = {}
    for term in valid:
        role = term.selection.role
        current = by_role.get(role)
        if current is None or term.selection.confidence > current.selection.confidence:
            by_role[role] = term
    return by_role
