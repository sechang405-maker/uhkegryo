import pytest
from types import SimpleNamespace
from uuid import uuid4

from backend.schemas.enums import Role
from backend.schemas.models import AgentResult, ReferencePlan, TermResult
from backend.services.conversation_context import next_state
from backend.services.conversation_memory import record
from backend.services.reference_update import merge_preserved, previous_terms, refresh_resolution, annotate


def term(name):
    return TermResult(role='pose', term_id=name, label_ko=name, label_en=name,
        plain_meaning_ko='pose', search_url='https://www.pinterest.com/search/pins/', pins=[])


def board(*names):
    return AgentResult(agent_status='success', reference_plan=ReferencePlan(terms=[term(n) for n in names]))


def test_add_same_role_constraint_keeps_legacy_constraint():
    state = {'constraints': {'pose': {'term_id': 'sitting', 'evidence': 'sit', 'source_job_id': str(uuid4())}}}
    update = SimpleNamespace(role=Role.POSE, term_id='aiming', evidence='aim', remove_term_ids=[])
    result = next_state({'state': state}, {'job_id': uuid4()}, SimpleNamespace(context_updates=[update]), board('aiming'))
    assert set(result['constraints']) == {'sitting', 'aiming'}
    assert result['constraints']['sitting']['role'] == 'pose'


def test_explicit_replacement_keeps_other_same_role_reference():
    previous = {'sitting': term('sitting'), 'aiming': term('aiming')}
    update = SimpleNamespace(role=Role.POSE, term_id='standing', evidence='stand', remove_term_ids=['sitting'])
    result = merge_preserved(board('standing'), previous, SimpleNamespace(context_updates=[update]))
    assert [t.term_id for t in result.reference_plan.terms] == ['aiming', 'standing']


def test_previous_map_and_selective_refresh_keep_both_pose_cards(snapshot_factory, card_factory):
    # Construct a legacy-shaped payload directly to test the read boundary.
    payload = board('sitting').model_dump(mode='json')
    payload['reference_plan']['terms'].append(term('aiming').model_dump(mode='json'))
    context = {'previous_result': payload, 'reference_action': 'refresh_terms', 'refresh_term_ids': ['sitting']}
    snapshot = snapshot_factory([card_factory('sitting'), card_factory('aiming')])
    previous = previous_terms(context, snapshot)
    assert set(previous) == {'sitting', 'aiming'}
    refreshed = refresh_resolution(previous, snapshot, context)
    assert [t.selection.term_id for t in refreshed.terms] == ['sitting']


def test_memory_record_retains_ten_independent_cards():
    payload = {'agent_status': 'success', 'reference_plan': {'terms': [term(str(i)).model_dump(mode='json') for i in range(10)]}}
    result = record({'final_payload_json': payload, 'status': 'completed', 'job_id': uuid4(), 'request_text': 'poses'})
    assert len(result['terms']) == 10


def test_annotation_distinguishes_cards_with_same_role():
    context = {'previous_result': board('sitting').model_dump(mode='json')}
    result = annotate(board('aiming'), context, {'aiming'})
    assert result.reference_update.replaced_term_ids == ['aiming']
    assert result.reference_update.removed_term_ids == ['sitting']


def test_annotation_roundtrip_covers_preserved_same_role_card():
    context = {'previous_result': board('sitting', 'aiming').model_dump(mode='json')}
    result = annotate(board('aiming', 'standing'), context, {'standing'})
    parsed = AgentResult.model_validate(result.model_dump(mode='json'))
    assert parsed.reference_update.preserved_term_ids == ['aiming']
    assert parsed.reference_update.removed_term_ids == ['sitting']


def test_legacy_clear_role_removes_all_its_independent_constraints():
    state = {'constraints': {
        name: {'role': 'pose', 'term_id': name, 'source_job_id': str(uuid4())}
        for name in ('sitting', 'aiming')}}
    update = SimpleNamespace(role=Role.POSE, term_id=None, evidence='clear poses', remove_term_ids=[])
    result = next_state({'state': state}, {'job_id': uuid4()}, SimpleNamespace(context_updates=[update]), board('standing'))
    assert result['constraints'] == {}


def test_refresh_missing_term_requests_clarification(snapshot_factory, card_factory):
    context = {'previous_result': board('sitting').model_dump(mode='json'),
               'reference_action': 'refresh_terms', 'refresh_term_ids': ['missing']}
    snapshot = snapshot_factory([card_factory('sitting')])
    assert refresh_resolution(previous_terms(context, snapshot), snapshot, context).status == 'clarify'


def test_memory_adapter_preserves_exact_card_refresh(monkeypatch):
    import asyncio
    import json
    from pathlib import Path
    from backend.schemas.memory import RecallQuery
    from backend.tests.test_llm_adapter import _adapter, _FakeCompletions, _FakeResponse
    transport = _FakeCompletions([_FakeResponse(json.dumps({'mode': 'none',
        'reference_action': 'refresh_terms', 'refresh_term_ids': ['sitting']}))])
    adapter = _adapter(transport)
    monkeypatch.setattr(adapter, '_resolve_prompt_path', lambda: Path(__file__).parents[2] / 'prompts/uhkegryo-interpreter-v4.md')
    result = asyncio.run(adapter.memory('classify', {'request_text': 'refresh sitting'}, RecallQuery,
        job_id=str(uuid4()), session_id=str(uuid4()), attempt=1, max_attempts=3))
    assert result.reference_action == 'refresh_terms'
    assert result.refresh_term_ids == ['sitting']


@pytest.mark.parametrize('removed', ['missing', 'body_card'])
def test_context_removal_rejects_unknown_or_wrong_role_target(snapshot_factory, card_factory, removed):
    import asyncio
    from backend.schemas.models import InterpretationOutput
    from backend.services.conversation_context import validate
    from backend.services.llm import LLMInvalidStructuredOutput
    output = InterpretationOutput(interpretation_state='select_terms', answer_text='change',
        selections=[{'role': 'pose', 'term_id': 'standing', 'evidence': ['change'], 'confidence': 1}],
        context_updates=[{'role': 'pose', 'term_id': 'standing', 'evidence': 'change', 'remove_term_ids': [removed]}])
    context = {'state': {'constraints': {'body': {'term_id': 'body_card', 'source_job_id': str(uuid4())}}}}
    snapshot = snapshot_factory([card_factory('standing')])
    with pytest.raises(LLMInvalidStructuredOutput):
        asyncio.run(validate(None, {'request_text': 'change'}, output, snapshot, context=context))


def test_context_bound_rejects_eleventh_card_before_commit(snapshot_factory, card_factory):
    import asyncio
    from backend.schemas.models import InterpretationOutput
    from backend.services.conversation_context import validate
    from backend.services.llm import LLMInvalidStructuredOutput
    output = InterpretationOutput(interpretation_state='select_terms', answer_text='change',
        selections=[{'role': 'pose', 'term_id': 'standing', 'evidence': ['change'], 'confidence': 1}],
        context_updates=[{'role': 'pose', 'term_id': 'standing', 'evidence': 'change'}])
    context = {'state': {'constraints': {str(i): {'role': 'pose', 'term_id': str(i)} for i in range(10)}}}
    snapshot = snapshot_factory([card_factory('standing')])
    with pytest.raises(LLMInvalidStructuredOutput):
        asyncio.run(validate(None, {'request_text': 'change'}, output, snapshot, context=context))



def test_valid_targeted_update_validates_and_preserves_sibling(snapshot_factory, card_factory):
    import asyncio
    from backend.schemas.models import InterpretationOutput
    from backend.services.conversation_context import validate
    output = InterpretationOutput(interpretation_state='select_terms', answer_text='change',
        selections=[{'role': 'pose', 'term_id': 'standing', 'evidence': ['change'], 'confidence': 1}],
        context_updates=[{'role': 'pose', 'term_id': 'standing', 'evidence': 'change', 'remove_term_ids': ['sitting']}])
    context = {'state': {'constraints': {name: {'role': 'pose', 'term_id': name} for name in ('sitting', 'aiming')}},
        'previous_result': board('sitting', 'aiming').model_dump(mode='json')}
    snapshot = snapshot_factory([card_factory('standing'), card_factory('sitting'), card_factory('aiming')])
    assert asyncio.run(validate(None, {'request_text': 'change'}, output, snapshot, context=context)).status == 'proceed'
    state = next_state(context, {'job_id': uuid4()}, output, board('standing'))
    assert set(state['constraints']) == {'aiming', 'standing'}


def test_database_roundtrip_preserves_same_role_cards_and_targeted_followup(snapshot_factory, card_factory):
    import asyncio
    from backend.schemas.enums import JobStatus
    from backend.schemas.models import InterpretationOutput
    from backend.services.conversation_memory import ConversationMemory
    from backend.services.conversation_context import validate
    from backend.services.job_repository import JobRepository
    from backend.services.session_repository import SessionRepository
    from backend.tests.test_conversation_sessions import database_case

    async def scenario(pool):
        jobs, memory = JobRepository(pool), ConversationMemory(pool)
        session = await SessionRepository(pool).create_session('multicard-storage-test')
        async def claim(text):
            await jobs.submit(session_id=session, request_text=text, idempotency_key=str(uuid4()))
            job = await jobs.claim_next()
            await jobs.update_status(job_id=str(job['job_id']), attempt=job['attempt'], status=JobStatus.VALIDATING)
            return job
        async def save(job, result, state):
            await jobs.update_status(job_id=str(job['job_id']), attempt=job['attempt'], status=JobStatus.RENDERING)
            await memory.complete(job, result, state)
        initial = await claim('sitting aiming slim')
        context = await memory.load(initial)
        body = term('slim').model_copy(update={'role': Role.BODY})
        result = AgentResult(agent_status='success', reference_plan=ReferencePlan(terms=[body, term('sitting'), term('aiming')]))
        updates = [SimpleNamespace(role=card.role, term_id=card.term_id, evidence=card.term_id, remove_term_ids=[])
                   for card in result.reference_plan.terms]
        await save(initial, result, next_state(context, initial, SimpleNamespace(context_updates=updates), result))
        followup = await claim('standing instead of sitting')
        restored = await memory.load(followup)
        assert set(restored['state']['constraints']) == {'sitting', 'aiming', 'slim'}
        assert [t['term_id'] for t in restored['previous_result']['reference_plan']['terms']] == ['slim', 'sitting', 'aiming']
        output = InterpretationOutput(interpretation_state='select_terms', answer_text='standing',
            selections=[{'role': 'pose', 'term_id': 'standing', 'evidence': ['standing'], 'confidence': 1}],
            context_updates=[{'role': 'pose', 'term_id': 'standing', 'evidence': 'standing instead of sitting',
                              'remove_term_ids': ['sitting']}])
        snapshot = snapshot_factory([card_factory(name) for name in ('sitting', 'aiming', 'standing')]
                                    + [card_factory('slim', role='body')])
        assert (await validate(memory, followup, output, snapshot, context=restored)).status == 'proceed'
        merged = merge_preserved(board('standing'), previous_terms(restored, snapshot), output)
        await save(followup, merged, next_state(restored, followup, output, merged))
        final_job = await claim('show my cards')
        final = await memory.load(final_job)
        assert set(final['state']['constraints']) == {'aiming', 'standing', 'slim'}
        assert [t['term_id'] for t in final['previous_result']['reference_plan']['terms']] == ['slim', 'aiming', 'standing']
        assert len(final['sources']) == 2
    asyncio.run(database_case(scenario))
