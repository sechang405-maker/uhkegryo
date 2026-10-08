"""TERM_CARD JSON 카탈로그 로드·시작 검증·불변 스냅샷 (docs/specs/term-card-catalog.md 기준).

- index.json과 index가 선언한 5개 역할 JSON(body·pose·view·perspective·layout)만 읽는다.
- 활성 조건 `runtime_eligible=true && mvp_status=active_in_current_contract`를 통과한 카드만
  `term_id -> card` 사전과 역할별 목록으로 로드한다. 요청 처리 중 파일을 다시 읽지 않는다.
- 검증 실패 시 `CatalogLoadError`(RuntimeError)를 던져 프로세스를 start 하지 않게 한다
  (fail-closed, 운영 원인 `CATALOG_INVALID_AT_STARTUP`).
- TERM_CARD는 DB에 적재하거나 외부 어휘·Getty 데이터를 병합하지 않는다.

T17 결정 사항: `requires_all_of`/`requires_any_of`가 참조하는 term_id가 활성 카탈로그에
존재하지 않으면 시작 검증에서 거부한다(구조 무결성 방어). 의미 충족 여부는 SKILL.md를 따른
LLM 판단 몫이며 결정론 코드는 재판정하지 않는다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from backend.schemas.enums import Role

REQUIRED_CARD_FIELDS = (
    "term_id",
    "role",
    "label_ko",
    "label_en",
    "query_fragments",
    "look_for",
    "confidence_gate",
    "requires_all_of",
    "requires_any_of",
    "runtime_eligible",
    "mvp_status",
)

REQUIRED_FEEDBACK_FIELDS = (
    "plain_meaning_ko",
    "selection_reason_template_ko",
    "reference_checkpoints_ko",
)

ACTIVE_MVP_STATUS = "active_in_current_contract"


class CatalogLoadError(RuntimeError):
    """카탈로그 구조·무결성 검증 실패. 시작을 거부해야 한다."""


@dataclass(frozen=True)
class CatalogSnapshot:
    """API·worker·MCP가 공유하는 읽기 전용 카탈로그 스냅샷."""

    dataset_version: str
    active_cards: dict[str, dict[str, Any]] = field(default_factory=dict)
    role_terms: dict[Role, list[str]] = field(default_factory=dict)
    roles_order: tuple[Role, ...] = ()
    feedback: dict[str, dict[str, str]] = field(default_factory=dict)
    direct_search_disabled: frozenset[str] = frozenset()

    @property
    def active_count(self) -> int:
        return len(self.active_cards)

    def get_active(self, term_id: str) -> dict[str, Any] | None:
        return self.active_cards.get(term_id)

    def is_direct_search_disabled(self, term_id: str) -> bool:
        return term_id in self.direct_search_disabled


def load_catalog(catalog_dir: Path) -> CatalogSnapshot:
    """카탈로그를 로드·검증하고 불변 스냅샷을 반환한다 (term-card-catalog AC-01~AC-05)."""
    index_path = catalog_dir / "index.json"
    if not index_path.exists():
        raise CatalogLoadError(f"index.json not found at {index_path}")

    try:
        with open(index_path, "r", encoding="utf-8") as f:
            index_data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        raise CatalogLoadError(f"index.json parse failed: {e}") from e

    if not isinstance(index_data, dict):
        raise CatalogLoadError("index.json의 최상위 구조가 객체여야 한다")

    categories = index_data.get("categories")
    if not isinstance(categories, list) or not categories:
        raise CatalogLoadError("index.categories가 비어 있거나 잘못된 타입이다")

    declared_roles: list[Role] = []
    files: list[Path] = []
    for cat in categories:
        if not isinstance(cat, dict) or "role" not in cat or "file" not in cat:
            raise CatalogLoadError(f"categories 항목에 role·file이 없다: {cat}")
        try:
            role = Role(cat["role"])
        except ValueError as e:
            raise CatalogLoadError(f"허용되지 않은 role: {cat['role']}") from e
        if role in declared_roles:
            raise CatalogLoadError(f"역할 중복 선언: {role}")
        declared_roles.append(role)
        files.append(catalog_dir / cat["file"])

    active_cards: dict[str, dict[str, Any]] = {}
    role_terms: dict[Role, list[str]] = {role: [] for role in declared_roles}
    seen_term_ids: set[str] = set()

    for role, file_path in zip(declared_roles, files):
        if not file_path.exists():
            raise CatalogLoadError(f"role file not found: {file_path}")
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                role_data = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            raise CatalogLoadError(f"{file_path.name} parse failed: {e}") from e

        for card in role_data.get("cards", []) or []:
            if not isinstance(card, dict):
                raise CatalogLoadError(f"{file_path.name}에 카드가 객체가 아님")
            term_id = card.get("term_id")
            _validate_card_required_fields(card, term_id, file_path.name)

            if str(card["role"]) != role.value:
                raise CatalogLoadError(
                    f"카드 role이 선언된 역할과 다르다: term_id={term_id}, role={card['role']} != {role.value}"
                )
            if term_id in seen_term_ids:
                raise CatalogLoadError(f"전역 중복 term_id: {term_id}")
            seen_term_ids.add(term_id)

            if not _is_active(card):
                continue  # 비활성 카드는 로드하지 않는다 (제거 없이 비활성화 배포 허용)

            if not card.get("query_fragments"):
                raise CatalogLoadError(f"활성 카드의 query_fragments가 비어 있다: term_id={term_id}")
            if not card.get("source_answer_draft") or not card.get("look_for"):
                raise CatalogLoadError(
                    f"활성 카드의 source_answer_draft·look_for가 비어 있다: term_id={term_id}"
                )
            if card["source_type"] != "team_card":
                raise CatalogLoadError(
                    f"모든 카드의 source_type은 team_card여야 한다: term_id={term_id}"
                )

            active_cards[term_id] = dict(card)
            role_terms[role].append(term_id)

    # requires_all_of / requires_any_of 참조 ID가 활성 카탈로그에 존재 (구조 무결성)
    for term_id, card in active_cards.items():
        references = [
            *(card.get("requires_all_of") or []),
            *(card.get("requires_any_of") or []),
        ]
        for ref in references:
            if not isinstance(ref, str) or ref not in active_cards:
                raise CatalogLoadError(
                    f"requires_*가 참조하는 term_id가 활성 카탈로그에 없다: "
                    f"term_id={term_id}, ref={ref}"
                )

    # active_term_feedback 검증 (AC-05)
    feedback_raw = index_data.get("active_term_feedback", {}) or {}
    feedback: dict[str, dict[str, str]] = {}
    for term_id, fb in feedback_raw.items():
        if term_id not in active_cards:
            raise CatalogLoadError(f"피드백 term_id가 활성 카드에 없다: {term_id}")
        if not isinstance(fb, dict):
            raise CatalogLoadError(f"피드백 구조가 객체가 아님: {term_id}")
        missing = [f for f in REQUIRED_FEEDBACK_FIELDS if not fb.get(f)]
        if missing:
            raise CatalogLoadError(f"피드백 필드 누락/빈 값: term_id={term_id}, fields={missing}")
        feedback[term_id] = {f: fb[f] for f in REQUIRED_FEEDBACK_FIELDS}

    psc = index_data.get("pinterest_search_contract", {}) or {}
    direct_disabled = psc.get("direct_search_disabled_term_ids", []) or []
    if not isinstance(direct_disabled, list):
        raise CatalogLoadError("pinterest_search_contract.direct_search_disabled_term_ids는 배열이어야 한다")

    return CatalogSnapshot(
        dataset_version=str(index_data.get("dataset_version", "unknown")),
        active_cards=active_cards,
        role_terms=role_terms,
        roles_order=tuple(declared_roles),
        feedback=feedback,
        direct_search_disabled=frozenset(direct_disabled),
    )


def _is_active(card: dict[str, Any]) -> bool:
    """활성 조건: runtime_eligible=true && mvp_status=active_in_current_contract."""
    return card.get("runtime_eligible") is True and card.get("mvp_status") == ACTIVE_MVP_STATUS


def _validate_card_required_fields(card: dict, term_id: Any, file_name: str) -> None:
    if not isinstance(term_id, str) or not term_id:
        raise CatalogLoadError(f"{file_name}에 term_id가 비어 있음")
    missing = [f for f in REQUIRED_CARD_FIELDS if f not in card]
    if missing:
        raise CatalogLoadError(f"필수 필드 누락: term_id={term_id}, fields={missing}")