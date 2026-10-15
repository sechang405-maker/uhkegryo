import asyncio
from types import SimpleNamespace
import pytest
from backend.schemas.enums import Role, ReasonCode
from backend.schemas.models import InterpretationSelection
from backend.services.agent_worker import AgentJobWorker
from backend.services import agent_worker
from backend.services.resolver import ResolutionResult, ValidatedTerm
from backend.services.response_assembler import RoleSearchOutcome, assemble
from backend.tests.test_agent_worker import FakeAdapter, FakeMcpGateway


def resolution(card_factory):
    return ResolutionResult(status='proceed', terms=[ValidatedTerm(
        selection=InterpretationSelection(role=Role.POSE, term_id=tid, evidence=['cue'], confidence=.9),
        card=card_factory(tid, role='pose', query_fragments=[tid]))
        for tid in ('pose_one', 'pose_two')])


def test_assembly_keeps_same_role_outcomes_separate(card_factory, snapshot_factory):
    resolved = resolution(card_factory)
    result = assemble(resolved, snapshot_factory([t.card for t in resolved.terms]), {
        'pose_one': RoleSearchOutcome(Role.POSE, code=ReasonCode.PIN_RESULTS_EMPTY),
        'pose_two': RoleSearchOutcome(Role.POSE, code=ReasonCode.PIN_SEARCH_UNAVAILABLE),
    })
    assert [t.reason_codes for t in result.reference_plan.terms] == [
        [ReasonCode.PIN_RESULTS_EMPTY], [ReasonCode.PIN_SEARCH_UNAVAILABLE]]


def test_local_search_preserves_each_term_and_fragments(monkeypatch, card_factory):
    class Provider:
        def __init__(self, **kwargs):
            pass
        async def search(self, role, fragments):
            return RoleSearchOutcome(role, code=(ReasonCode.PIN_RESULTS_EMPTY if fragments == ('pose_one',)
                                                else ReasonCode.PIN_SEARCH_UNAVAILABLE))
    monkeypatch.setattr(agent_worker, 'SearXNGPinterestSearchProvider', Provider)
    worker = AgentJobWorker(None, None, local_search_url='http://unused')
    outcomes = asyncio.run(worker._local_search_outcomes(resolution(card_factory), {}))
    assert set(outcomes) == {'pose_one', 'pose_two'}
    assert outcomes['pose_one'].code == ReasonCode.PIN_RESULTS_EMPTY
    assert outcomes['pose_two'].code == ReasonCode.PIN_SEARCH_UNAVAILABLE


def test_mcp_search_preserves_same_role_terms(card_factory):
    calls = [{'id': tid, 'name': 'search_pinterest_pins', 'arguments': {
        'role': 'pose', 'term_id': tid, 'query_fragments': [tid]}}
        for tid in ('pose_one', 'pose_two')]
    gateway = FakeMcpGateway([{'role': 'pose', 'pins': [], 'code': ReasonCode.PIN_RESULTS_EMPTY.value}] * 2)
    worker = AgentJobWorker(None, None, adapter=FakeAdapter(tool_calls=[calls]), mcp_gateway=gateway)
    outcomes = asyncio.run(worker._search_outcomes(resolution(card_factory), request_text='cue'))
    assert set(outcomes) == {'pose_one', 'pose_two'}
    assert [args['query_fragments'] for _, args in gateway.calls] == [['pose_one'], ['pose_two']]


def test_ambiguous_role_outcome_is_not_copied_to_both_cards(card_factory, snapshot_factory):
    resolved = resolution(card_factory)
    result = assemble(resolved, snapshot_factory([t.card for t in resolved.terms]), {
        Role.POSE: RoleSearchOutcome(Role.POSE, code=ReasonCode.PIN_RESULTS_EMPTY)})
    assert all(not term.reason_codes for term in result.reference_plan.terms)


def test_mcp_retries_only_failed_term(monkeypatch, card_factory):
    def call(tid):
        return {'id': tid, 'name': 'search_pinterest_pins', 'arguments': {
            'role': 'pose', 'term_id': tid, 'query_fragments': [tid]}}
    async def no_wait(*args):
        pass
    monkeypatch.setattr(AgentJobWorker, '_search_backoff', no_wait)
    gateway = FakeMcpGateway([
        {'role': 'pose', 'pins': [], 'code': ReasonCode.PIN_RESULTS_EMPTY.value},
        {'role': 'pose', 'pins': [], 'code': ReasonCode.PIN_SEARCH_UNAVAILABLE.value},
        {'role': 'pose', 'pins': [], 'code': ReasonCode.PIN_RESULTS_EMPTY.value}])
    worker = AgentJobWorker(None, None, adapter=FakeAdapter(tool_calls=[
        [call('pose_one'), call('pose_two')], [call('pose_two')]]), mcp_gateway=gateway)
    outcomes = asyncio.run(worker._search_outcomes(resolution(card_factory), request_text='cue'))
    assert set(outcomes) == {'pose_one', 'pose_two'}
    assert [a['query_fragments'] for _, a in gateway.calls] == [['pose_one'], ['pose_two'], ['pose_two']]


def test_mcp_rejects_missing_identity_for_same_role(card_factory):
    from backend.services.llm import LLMInvalidStructuredOutput
    gateway = FakeMcpGateway([])
    worker = AgentJobWorker(None, None, adapter=FakeAdapter(tool_calls=[[{
        'id': 'ambiguous', 'name': 'search_pinterest_pins', 'arguments': {
            'role': 'pose', 'query_fragments': ['pose_two']}}]]), mcp_gateway=gateway)
    with pytest.raises(LLMInvalidStructuredOutput):
        asyncio.run(worker._search_outcomes(resolution(card_factory), request_text='cue'))
    assert gateway.calls == []


def test_mcp_supports_ten_independent_same_role_searches(card_factory):
    resolved = resolution(card_factory)
    resolved.terms = [ValidatedTerm(
        selection=InterpretationSelection(role=Role.POSE, term_id=f'pose_{i}', evidence=['cue'], confidence=.9),
        card=card_factory(f'pose_{i}', role='pose', query_fragments=[f'pose_{i}'])) for i in range(10)]
    calls = [{'id': t.selection.term_id, 'name': 'search_pinterest_pins', 'arguments': {
        'role': 'pose', 'term_id': t.selection.term_id, 'query_fragments': t.card['query_fragments']}}
        for t in resolved.terms]
    gateway = FakeMcpGateway([{'role': 'pose', 'pins': [], 'code': ReasonCode.PIN_RESULTS_EMPTY.value} for _ in calls])
    worker = AgentJobWorker(None, None, adapter=FakeAdapter(tool_calls=[calls]), mcp_gateway=gateway)
    outcomes = asyncio.run(worker._search_outcomes(resolved, request_text='cue'))
    assert set(outcomes) == {f'pose_{i}' for i in range(10)}
    assert [a['query_fragments'] for _, a in gateway.calls] == [[f'pose_{i}'] for i in range(10)]


@pytest.mark.parametrize("action", ["refresh_all", "refresh_terms"])
def test_refresh_excludes_only_each_cards_own_pins(monkeypatch, card_factory, snapshot_factory, action):
    from backend.schemas.models import PinResult
    from backend.tests.test_agent_worker import FakeJobs, FakeRecovery, _worker
    resolved = resolution(card_factory)
    snapshot = snapshot_factory([t.card for t in resolved.terms])
    prior = assemble(resolved, snapshot)
    for index, term in enumerate(prior.reference_plan.terms):
        term.pins = [PinResult(pin_id=str(index * 10 + i),
            pin_url=f'https://www.pinterest.com/pin/{index * 10 + i}/', status='available')
            for i in range(8)]
    context = {'state': {}, 'reference_action': action, 'refresh_term_ids': ['pose_one'],
               'previous_result': prior.model_dump(mode='json')}
    async def prepare(*args):
        return context
    async def recall(*args):
        return None, False
    monkeypatch.setattr(agent_worker.conversation_context, 'prepare', prepare)
    monkeypatch.setattr(agent_worker.conversation_context, 'recall', recall)
    jobs, recovery = FakeJobs(), FakeRecovery()
    worker = _worker(monkeypatch, jobs, recovery, snapshot, FakeAdapter())
    captured = {}
    async def search(resolution, **kwargs):
        captured.update(kwargs['exclude_pin_ids'])
        return {}
    worker._search_outcomes = search
    asyncio.run(worker.run_once())
    assert captured == {term.term_id: [pin.pin_id for pin in term.pins]
                        for term in prior.reference_plan.terms}
    assert recovery.failures == []
    if action == "refresh_terms":
        assert "요청한 카드" in jobs.writes[-1][1].answer_text
        assert "전체" not in jobs.writes[-1][1].answer_text
