"""Pinterest 검색 provider 계약과 외부 호출 없는 테스트용 구현."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Protocol

from backend.schemas.enums import Role
from backend.schemas.models import PinResult
from backend.services.response_assembler import RoleSearchOutcome


class PinterestProvider(Protocol):
    """후속 공개 검색·widget provider가 구현할 비동기 경계."""

    async def search(
        self, role: Role, query_fragments: tuple[str, ...]
    ) -> RoleSearchOutcome:
        """활성 카드의 검색 조각으로 역할별 Pin 결과를 반환한다."""


@dataclass(frozen=True)
class ProviderCall:
    role: Role
    query_fragments: tuple[str, ...]


class FakePinterestProvider:
    """역할별 고정 결과를 반환하며 네트워크·저장소에 접근하지 않는다."""

    def __init__(self, results: Mapping[Role, RoleSearchOutcome]) -> None:
        self._results = {role: _copy_outcome(outcome) for role, outcome in results.items()}
        for role, outcome in self._results.items():
            if role != outcome.role:
                raise ValueError("fake 결과의 역할이 매핑 키와 다릅니다")
        self.calls: list[ProviderCall] = []

    async def search(
        self, role: Role, query_fragments: tuple[str, ...]
    ) -> RoleSearchOutcome:
        if not query_fragments or any(not part.strip() for part in query_fragments):
            raise ValueError("활성 카드의 비어 있지 않은 query_fragments가 필요합니다")
        self.calls.append(ProviderCall(role, query_fragments))
        return _copy_outcome(self._results[role])


def _copy_outcome(outcome: RoleSearchOutcome) -> RoleSearchOutcome:
    return RoleSearchOutcome(
        role=outcome.role,
        pins=[PinResult.model_validate(pin.model_dump()) for pin in outcome.pins],
        code=outcome.code,
    )
