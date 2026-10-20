import asyncio
from uuid import UUID

import pytest

from backend.schemas.models import InterpretationOutput
from backend.services import conversation_context
from backend.services.llm import LLMInvalidStructuredOutput


OLD = '00000000-0000-4000-8000-000000000001'


class Memory:
    def __init__(self, rows):
        self.rows = rows
        self.reads = []

    async def records(self, job, ids):
        self.reads.append(tuple(map(str, ids)))
        return [row for row in self.rows if row['job_id'] in set(map(str, ids))]


def context(row=None, constraints=None):
    return dict(state={'constraints': constraints or {}}, recent=[row] if row else [],
                sources=[], previous_result={})


def row(message='서 있는 자세는 어때요?', request='캐릭터 자세를 고민 중이야'):
    return dict(job_id=OLD, request_text=request, terms=[], message=message, question=None)


def selected(evidence='서 있는', source=OLD):
    return InterpretationOutput(interpretation_state='select_terms', answer_text='자세 자료를 찾았어요.',
        selections=[dict(role='pose', term_id='pose_standing', evidence=[evidence],
                         confidence=.9, source_job_id=source)])


def test_immediate_explicitly_adopted_suggestion_is_verified(card_factory, snapshot_factory):
    original = row()
    memory = Memory([original])
    resolution = asyncio.run(conversation_context.validate(memory,
        {'request_text': '그런 포즈 보고 싶어'}, selected(),
        snapshot_factory([card_factory('pose_standing', label_ko='서 있는')]), context=context(original)))
    assert resolution.status == 'proceed'
    assert memory.reads and all(ids == (OLD,) for ids in memory.reads)


@pytest.mark.parametrize('text,latest,original', [
    ('서 있는 자세는 어떻게 그려?', row(), row()),
    ('그런 포즈 보고 싶어', {**row(), 'job_id': 'newer'}, row()),
    ('그런 포즈 보고 싶어', None, row()),
    ('그런 포즈 보고 싶어', row(), {**row(), 'recommendation_group': {'candidates': []}}),
    ('그런 포즈 보고 싶어', row(), row('서 있는 자세는 추천하지 않아요.')),
])
def test_assistant_text_is_not_general_search_evidence(card_factory, snapshot_factory, text, latest, original):
    with pytest.raises(LLMInvalidStructuredOutput):
        asyncio.run(conversation_context.validate(Memory([original]), {'request_text': text}, selected(),
            snapshot_factory([card_factory('pose_standing', label_ko='서 있는')]), context=context(latest)))


def test_fabricated_source_is_rejected(card_factory, snapshot_factory):
    with pytest.raises(LLMInvalidStructuredOutput):
        asyncio.run(conversation_context.validate(Memory([]), {'request_text': '그런 포즈 찾아줘'}, selected(),
            snapshot_factory([card_factory('pose_standing')]), context=context(row())))


def chat():
    return InterpretationOutput(interpretation_state='drawing_chat', answer_text='그림 이야기를 해요.')


def test_misrouted_draw_desire_uses_current_valid_card_without_missing_categories(card_factory, snapshot_factory):
    output = asyncio.run(conversation_context.reference_fallback(Memory([]),
        {'request_text': '서 있는 캐릭터를 그리고 싶어'}, chat(),
        snapshot_factory([card_factory('pose_standing', label_ko='서 있는')]), context()))
    assert [item.term_id for item in output.selections] == ['pose_standing']
    assert output.selections[0].source_job_id is None


def test_followup_uses_original_user_conditions_and_exact_source(card_factory, snapshot_factory):
    original = row(request='서 있는 캐릭터야. 지금은 검색하지 말아줘')
    memory = Memory([original])
    output = asyncio.run(conversation_context.reference_fallback(memory,
        {'request_text': '이런 캐릭터를 그리고 싶어'}, chat(),
        snapshot_factory([card_factory('pose_standing', label_ko='서 있는')]), context(original)))
    assert [item.term_id for item in output.selections] == ['pose_standing']
    assert output.selections[0].source_job_id == UUID(OLD)
    assert memory.reads and all(ids == (OLD,) for ids in memory.reads)


def test_bare_find_reuses_immediate_related_user_description(card_factory, snapshot_factory):
    original = row(request='서 있는 캐릭터야')
    output = asyncio.run(conversation_context.reference_fallback(Memory([original]),
        {'request_text': '찾아줘'}, chat(),
        snapshot_factory([card_factory('pose_standing', label_ko='서 있는')]), context(original)))
    assert [item.term_id for item in output.selections] == ['pose_standing']
    assert output.selections[0].source_job_id == UUID(OLD)


def test_bare_find_new_session_asks_one_minimal_question(snapshot_factory):
    output = asyncio.run(conversation_context.reference_fallback(Memory([]), {'request_text': '찾아줘'},
        chat(), snapshot_factory([]), context()))
    assert output.interpretation_state == 'needs_clarification'
    assert output.clarifying_question.count('?') == 1


def test_chat_fallback_can_use_explicitly_adopted_immediate_suggestion(card_factory, snapshot_factory):
    original = row()
    output = asyncio.run(conversation_context.reference_fallback(Memory([original]),
        {'request_text': '그런 포즈 보고 싶어'}, chat(),
        snapshot_factory([card_factory('pose_standing', label_ko='서 있는')]), context(original)))
    assert [item.term_id for item in output.selections] == ['pose_standing']
    assert output.selections[0].source_job_id == UUID(OLD)


@pytest.mark.parametrize('text', ['새 주제로 귀여운 얼굴을 그리고 싶어',
    '귀여운 얼굴을 그리고 싶어', '서 있는 건 빼고 그리고 싶어', '어떻게 그려?', '검색하지 마'])
def test_no_invention_or_restoration_without_usable_evidence(card_factory, snapshot_factory, text):
    output = chat()
    actual = asyncio.run(conversation_context.reference_fallback(Memory([]), {'request_text': text}, output,
        snapshot_factory([card_factory('pose_standing', label_ko='서 있는')]), context()))
    if text in ('어떻게 그려?', '검색하지 마'):
        assert actual == output
    else:
        assert actual.interpretation_state == 'needs_clarification'
        assert actual.selections == []


def test_new_face_subject_does_not_borrow_prior_standing(card_factory, snapshot_factory):
    original = row(request='서 있는 캐릭터')
    output = chat()
    actual = asyncio.run(conversation_context.reference_fallback(Memory([original]),
        {'request_text': '이번에는 얼굴만 그리고 싶어'}, output,
        snapshot_factory([card_factory('pose_standing', label_ko='서 있는')]), context(original)))
    assert actual.interpretation_state == 'needs_clarification'
    assert actual.selections == []


def test_old_source_rejected_after_topic_reset(card_factory, snapshot_factory):
    state = context(row(request='서 있는'))
    state['_recommendation_topic_reset'] = True
    with pytest.raises(LLMInvalidStructuredOutput):
        asyncio.run(conversation_context.validate(Memory([row(request='서 있는')]),
            {'request_text': '새 주제로 찾아줘'}, selected(),
            snapshot_factory([card_factory('pose_standing', label_ko='서 있는')]), context=state))


def test_worker_repairs_chat_route_to_reference_search(monkeypatch, card_factory, snapshot_factory):
    from backend.tests.test_agent_worker import JOB, FakeJobs, FakeRecovery, FakeAdapter, _worker
    from backend.services.response_assembler import RoleSearchOutcome
    from backend.schemas.enums import Role
    jobs, recovery = FakeJobs({**JOB, 'request_text': '서 있는 캐릭터를 그리고 싶어'}), FakeRecovery()
    worker = _worker(monkeypatch, jobs, recovery,
        snapshot_factory([card_factory('pose_standing', label_ko='서 있는')]), FakeAdapter(chat()))
    asyncio.run(worker.run_once(search_outcomes={'pose_standing': RoleSearchOutcome(role=Role.POSE)}))
    assert recovery.failures == []
    assert jobs.writes[-1][1].reference_plan is not None
    assert jobs.writes[-1][1].reference_plan.terms[0].term_id == 'pose_standing'


def test_explicit_removal_cannot_be_restored_from_original_source(card_factory, snapshot_factory):
    original = row(request='서 있는 캐릭터')
    output = selected().model_copy(update={'context_updates': []})
    state = context(original)
    state['recent'].append({**row(request='서 있는 건 빼줘'), 'job_id': 'latest'})
    with pytest.raises(LLMInvalidStructuredOutput):
        asyncio.run(conversation_context.validate(Memory([original]), {'request_text': '그런 포즈 찾아줘'},
            output, snapshot_factory([card_factory('pose_standing', label_ko='서 있는')]), context=state))


def test_missing_detail_fallback_explains_partial_conditions(card_factory, snapshot_factory):
    output = InterpretationOutput(interpretation_state='needs_clarification',
        clarification_type='insufficient_visual_evidence', clarifying_question='구도는 어떤가요?',
        unresolved_constraints=['구도'])
    repaired = asyncio.run(conversation_context.reference_fallback(Memory([]),
        {'request_text': '서 있는 캐릭터를 그리고 싶어'}, output,
        snapshot_factory([card_factory('pose_standing', label_ko='서 있는')]), context()))
    assert repaired.interpretation_state == 'select_terms'
    assert '서 있는' in repaired.answer_text
    assert '확정되지 않은 조건' in repaired.answer_text


def test_success_persists_original_adopted_source_and_literal_evidence(card_factory, snapshot_factory):
    from backend.services.response_assembler import assemble
    original = row()
    snapshot = snapshot_factory([card_factory('pose_standing', label_ko='서 있는')])
    output = selected()
    resolution = asyncio.run(conversation_context.validate(Memory([original]),
        {'request_text': '그런 포즈 보고 싶어'}, output, snapshot, context=context(original)))
    state = conversation_context.next_state(context(original), {'job_id': 'new'}, output,
        assemble(resolution, snapshot, answer_text=output.answer_text))
    assert state['constraints']['pose_standing']['source_job_id'] == OLD
    assert state['constraints']['pose_standing']['evidence'] == '서 있는'
    later = {**context(row(request='그런 포즈 보고 싶어')), 'state': state}
    later['recent'][-1]['job_id'] = 'new'
    assert asyncio.run(conversation_context.validate(Memory([original]),
        {'request_text': '그 자세 그대로 찾아줘'}, output, snapshot, context=later)).status == 'proceed'


@pytest.mark.parametrize('text', ['서 있는 자세는 어떻게 그려?',
    '서 있는 캐릭터는 안 그리고 싶어', '서 있는 캐릭터를 찾아줘라는 문장을 번역해줘'])
def test_worker_does_not_execute_misrouted_explicit_non_search(monkeypatch, card_factory, snapshot_factory, text):
    from backend.tests.test_agent_worker import JOB, FakeJobs, FakeRecovery, FakeAdapter, _worker
    jobs, recovery = FakeJobs({**JOB, 'request_text': text}), FakeRecovery()
    worker = _worker(monkeypatch, jobs, recovery,
        snapshot_factory([card_factory('pose_standing', label_ko='서 있는')]),
        FakeAdapter(selected(source=None)))
    asyncio.run(worker.run_once(search_outcomes={}))
    assert all(status != 'searching' for status, _, _ in jobs.writes)
    assert recovery.failures
    error = recovery.failures[0]['error']
    assert isinstance(error, LLMInvalidStructuredOutput)
    assert error.feedback[0]['code'] == 'reference_intent_conflict'


def test_negated_removal_preserves_but_real_removal_excludes():
    assert not conversation_context.explicitly_excluded('정면은 빼지 말고 유지해서 찾아줘', '정면')
    assert conversation_context.explicitly_excluded('정면은 빼고 찾아줘', '정면')


def test_current_correction_excludes_rejected_standing(card_factory, snapshot_factory):
    snapshot = snapshot_factory([card_factory('pose_standing', label_ko='서 있는'),
        card_factory('pose_sitting', label_ko='앉은')])
    output = asyncio.run(conversation_context.reference_fallback(Memory([]),
        {'request_text': '서 있는 게 아니라 앉은 캐릭터를 그리고 싶어'}, chat(), snapshot, context()))
    assert [item.term_id for item in output.selections] == ['pose_sitting']


def test_negated_removal_retains_reference_through_fallback_and_validation(card_factory, snapshot_factory):
    snapshot = snapshot_factory([card_factory('view_front', role='composition', label_ko='정면')])
    original = row(request='정면 캐릭터')
    state = context(original, {'view_front': dict(role='composition', term_id='view_front',
        source_job_id=OLD, evidence='정면')})
    text = '정면은 빼지 말고 유지해서 찾아줘'
    output = asyncio.run(conversation_context.reference_fallback(Memory([original]),
        {'request_text': text}, chat(), snapshot, state))
    assert [item.term_id for item in output.selections] == ['view_front']
    assert asyncio.run(conversation_context.validate(Memory([original]), {'request_text': text},
        output, snapshot, context=state)).status == 'proceed'


@pytest.mark.parametrize('persisted', [False, True])
@pytest.mark.parametrize('known_board', [False, True])
def test_real_catalog_current_orientation_keeps_independent_framing(persisted, known_board):
    from pathlib import Path
    from backend.services.catalog_repository import load_catalog
    from backend.services.reference_update import merge_preserved, previous_terms
    from backend.services.resolver import resolve
    from backend.services.response_assembler import assemble
    snapshot = load_catalog(Path(__file__).resolve().parents[2] / 'docs/domains/illustration-reference/term-cards')
    ids = ['pose_standing', 'view_three_quarter', 'view_full_body']
    cards = [snapshot.get_active(term_id) for term_id in ids]
    assert all(cards)
    description = ' '.join(card['label_ko'] for card in cards)
    original = row(request=description)
    prior = InterpretationOutput(interpretation_state='select_terms', answer_text='기존 조건', selections=[
        dict(role=card['role'], term_id=card['term_id'], evidence=[card['label_ko']], confidence=1)
        for card in cards])
    baseline = assemble(resolve(prior, snapshot, request_text=description), snapshot, answer_text='기존 조건')
    state = context(original)
    if known_board:
        state['previous_result'] = baseline.model_dump(mode='json')
    if persisted:
        state['state']['constraints'] = {card['term_id']: dict(role=card['role'], term_id=card['term_id'],
            evidence=card['label_ko'], source_job_id=OLD) for card in cards}
    text = snapshot.get_active('view_front')['label_ko'] + '으로 바꿔서 찾아줘'
    output = asyncio.run(conversation_context.reference_fallback(Memory([original]),
        {'request_text': text}, chat(), snapshot, state))
    expected = {'pose_standing', 'view_front', 'view_full_body'}
    assert {item.term_id for item in output.selections} == expected
    resolved = asyncio.run(conversation_context.validate(Memory([original]), {'request_text': text},
        output, snapshot, context=state))
    result = merge_preserved(assemble(resolved, snapshot, answer_text=output.answer_text),
        previous_terms(state, snapshot), output)
    assert {item.term_id for item in result.reference_plan.terms} == expected
    next_state = conversation_context.next_state(state, {'job_id': 'new'}, output, result)
    assert set(next_state['constraints']) == expected
    assert next_state['constraints']['view_front']['source_job_id'] == 'new'
    assert next_state['constraints']['view_full_body']['source_job_id'] == OLD
    removed = {term_id for update in output.context_updates for term_id in update.remove_term_ids}
    assert removed == ({'view_three_quarter'} if persisted or known_board else set())


@pytest.mark.parametrize('misroute', ['chat', 'clarify'])
def test_exact_live_natural_korean_context_and_front_correction(misroute):
    from pathlib import Path
    from backend.services.catalog_repository import load_catalog
    from backend.services.reference_update import merge_preserved, previous_terms
    from backend.services.response_assembler import assemble
    snapshot = load_catalog(Path(__file__).resolve().parents[2] / 'docs/domains/illustration-reference/term-cards')
    original = row(request='서 있는 캐릭터를 3/4 방향으로 그리고 싶어. 지금은 검색하지 말고 이런 느낌으로 연습하려는 생각만 정리해줘.',
        message='서 있는 캐릭터의 **3/4 뷰** 연습으로 정리하면 좋아요.')
    memory = Memory([original])
    first_context = context(original)
    misrouted = chat() if misroute == 'chat' else InterpretationOutput(interpretation_state='needs_clarification',
        clarification_type='insufficient_visual_evidence', unresolved_constraints=['자세와 방향'],
        clarifying_question='캐릭터 자세나 보는 방향은 어떤가요?')
    text = '이런 캐릭터를 그리고 싶어'
    output = asyncio.run(conversation_context.reference_fallback(memory, {'request_text': text},
        misrouted, snapshot, first_context))
    assert {item.term_id for item in output.selections} == {'pose_standing', 'view_three_quarter'}
    assert all(item.source_job_id == UUID(OLD) for item in output.selections)
    assert {item.evidence[0] for item in output.selections} == {'서 있는', '3/4 방향'}
    resolution = asyncio.run(conversation_context.validate(memory, {'request_text': text}, output,
        snapshot, context=first_context))
    result = assemble(resolution, snapshot, answer_text=output.answer_text)
    second_id = '00000000-0000-4000-8000-000000000002'
    state = conversation_context.next_state(first_context, {'job_id': second_id}, output, result)
    continued = dict(state=state, recent=[original, {**row(request=text), 'job_id': second_id}],
        previous_result=result.model_dump(mode='json'), sources=[])
    next_text = '정면으로 바꿔서 찾아줘'
    changed = asyncio.run(conversation_context.reference_fallback(memory, {'request_text': next_text},
        chat(), snapshot, continued))
    assert {item.term_id for item in changed.selections} == {'pose_standing', 'view_front'}
    resolved = asyncio.run(conversation_context.validate(memory, {'request_text': next_text},
        changed, snapshot, context=continued))
    final = merge_preserved(assemble(resolved, snapshot, answer_text=changed.answer_text),
        previous_terms(continued, snapshot), changed)
    assert {item.term_id for item in final.reference_plan.terms} == {'pose_standing', 'view_front'}


@pytest.mark.parametrize('description,expected', [
    ('"서 있는 캐릭터를 3/4 방향으로"라는 문장이야', set()),
    ("'서 있는 캐릭터를 3/4 방향으로'라는 예시야", set()),
    ('서 있는 건 빼고 3/4 방향 캐릭터를 생각하고 있어', {'view_three_quarter'}),
])
def test_real_aliases_preserve_quote_and_negative_guards(description, expected):
    from pathlib import Path
    from backend.services.catalog_repository import load_catalog
    snapshot = load_catalog(Path(__file__).resolve().parents[2] / 'docs/domains/illustration-reference/term-cards')
    original = row(request=description, message='')
    output = asyncio.run(conversation_context.reference_fallback(Memory([original]),
        {'request_text': '이런 캐릭터를 그리고 싶어'}, chat(), snapshot, context(original)))
    assert {item.term_id for item in output.selections} == expected


@pytest.mark.parametrize('middle,expected', [
    ('이런 캐릭터를 그리고 싶어', {'pose_standing', 'view_three_quarter'}),
    ('이번에는 얼굴만 그리고 싶어', set()),
    ('서 있는 조건은 빼줘', set()),
])
def test_retry_skips_only_pure_pointer_clarification_within_recent_context(middle, expected):
    from pathlib import Path
    from backend.services.catalog_repository import load_catalog
    snapshot = load_catalog(Path(__file__).resolve().parents[2] / 'docs/domains/illustration-reference/term-cards')
    original = row(request='서 있는 캐릭터를 3/4 방향으로 그리고 싶어. 지금은 검색하지 말고 생각만 정리해줘.', message='')
    retry_context = context(original)
    retry_context['recent'].append({**row(request=middle, message=''),
        'job_id': '00000000-0000-4000-8000-000000000002', 'question': '자세나 보는 방향을 알려주시겠어요?'})
    retry_context['state']['pending_question'] = '자세나 보는 방향을 알려주시겠어요?'
    memory = Memory([original])
    output = asyncio.run(conversation_context.reference_fallback(memory,
        {'request_text': '이런 캐릭터를 그리고 싶어'}, chat(), snapshot, retry_context))
    assert {item.term_id for item in output.selections} == expected
    if expected:
        assert all(item.source_job_id == UUID(OLD) for item in output.selections)
        assert memory.reads and all(ids == (OLD,) for ids in memory.reads)


@pytest.mark.parametrize('question', [None, '어떤 자세를 원하세요?'])
def test_pointer_row_with_substantive_assistant_suggestion_is_not_skipped(question):
    from pathlib import Path
    from backend.services.catalog_repository import load_catalog
    snapshot = load_catalog(Path(__file__).resolve().parents[2] / 'docs/domains/illustration-reference/term-cards')
    original = row(request='서 있는 캐릭터를 3/4 방향으로 생각 중이야', message='')
    suggestion = {**row(request='이런 캐릭터를 그리고 싶어', message='앉은 자세는 어때요?'),
        'job_id': '00000000-0000-4000-8000-000000000002', 'question': question}
    state = context(original)
    state['recent'].append(suggestion)
    memory = Memory([original, suggestion])
    output = asyncio.run(conversation_context.reference_fallback(memory,
        {'request_text': '그런 포즈 보고 싶어'}, chat(), snapshot, state))
    assert [item.term_id for item in output.selections] == ['pose_sitting']
    assert output.selections[0].source_job_id == UUID(suggestion['job_id'])
    assert memory.reads and all(ids == (suggestion['job_id'],) for ids in memory.reads)


def test_pointer_row_without_clarification_or_suggestion_is_a_context_boundary():
    original = row(request='서 있는 캐릭터야', message='')
    latest = {**row(request='이런 캐릭터를 그리고 싶어', message=''),
        'job_id': '00000000-0000-4000-8000-000000000002'}
    assert conversation_context.related_reference_record([original, latest]) is latest
