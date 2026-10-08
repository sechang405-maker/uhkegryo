"""PR-47: fake provider 결과가 기존 resolver·assembler 계약을 통과한다."""

import asyncio

import pytest

from backend.schemas.enums import AgentStatus, InterpretationState, PinStatus, Role
from backend.schemas.models import InterpretationOutput, InterpretationSelection, PinResult
from backend.services.pinterest_provider import FakePinterestProvider, PinterestProvider
from backend.services.response_assembler import RoleSearchOutcome, assemble
from backend.services.resolver import resolve


def _pin() -> PinResult:
    return PinResult(
        pin_id="123",
        pin_url="https://www.pinterest.com/pin/123/",
        status=PinStatus.AVAILABLE,
        thumbnail_url="https://images.example/123.jpg",
    )


def test_fake_result_assembles_pin_contract(snapshot_factory, card_factory):
    card = card_factory("pose_contrapposto", role="pose")
    snapshot = snapshot_factory([card])
    interpretation = InterpretationOutput(
        interpretation_state=InterpretationState.SELECT_TERMS,
        clarification_type=None,
        selections=[InterpretationSelection(
            role=Role.POSE, term_id="pose_contrapposto", evidence=["한쪽 다리에 체중"], confidence=0.9
        )],
        unresolved_constraints=[],
        clarifying_question=None,
    )
    provider: PinterestProvider = FakePinterestProvider({
        Role.POSE: RoleSearchOutcome(role=Role.POSE, pins=[_pin()])
    })
    outcome = asyncio.run(provider.search(Role.POSE, tuple(card["query_fragments"])))
    result = assemble(
        resolve(interpretation, snapshot, request_text="한쪽 다리에 체중"),
        snapshot,
        {Role.POSE: outcome},
    )

    assert result.agent_status is AgentStatus.SUCCESS
    pin = result.reference_plan.terms[0].pins[0]
    assert (pin.pin_id, pin.pin_url, pin.status) == (
        "123", "https://www.pinterest.com/pin/123/", PinStatus.AVAILABLE
    )
    assert len(result.reference_plan.terms[0].pins) == 1


def test_fake_returns_independent_copies_and_rejects_missing_role():
    provider = FakePinterestProvider({
        Role.POSE: RoleSearchOutcome(role=Role.POSE, pins=[_pin()])
    })
    first = asyncio.run(provider.search(Role.POSE, ("contrapposto pose",)))
    first.pins[0].pin_id = "changed"
    first.pins.clear()
    second = asyncio.run(provider.search(Role.POSE, ("contrapposto pose",)))
    assert [pin.pin_id for pin in second.pins] == ["123"]
    assert provider.calls[0].query_fragments == ("contrapposto pose",)
    with pytest.raises(KeyError):
        asyncio.run(provider.search(Role.BODY, ("slim body",)))


def test_fake_rejects_role_mismatch_and_empty_fragments():
    with pytest.raises(ValueError, match="역할"):
        FakePinterestProvider({Role.BODY: RoleSearchOutcome(role=Role.POSE)})
    provider = FakePinterestProvider({Role.POSE: RoleSearchOutcome(role=Role.POSE)})
    with pytest.raises(ValueError, match="query_fragments"):
        asyncio.run(provider.search(Role.POSE, ()))
