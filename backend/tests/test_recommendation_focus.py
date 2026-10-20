"""Recommendation focus and delegated choice without external services."""
from uuid import uuid4

import pytest

from backend.tests.test_recommendations import setup, handle, JOB, Memory, draft
from backend.services import recommendations
from backend.schemas.models import InterpretationOutput
from backend.services.llm import LLMInvalidStructuredOutput
import asyncio


@pytest.mark.parametrize('text', ['네가 골라서 찾아줘', '좋은 걸로 찾아줘', '알아서 골라 찾아줘'])
def test_delegated_choice_searches_one_current_candidate(snapshot_factory, card_factory, text):
    snapshot, group, context = setup(snapshot_factory, card_factory)
    decision = handle(snapshot, group, context, text)
    assert [term.selection.term_id for term in decision.resolution.terms] == ['stand']
    assert '서기' in decision.interpretation.answer_text


def test_source_bound_last_adoption_is_focus_for_short_request(snapshot_factory, card_factory):
    snapshot, group, context = setup(snapshot_factory, card_factory)
    chosen = handle(snapshot, group, context)
    context['state'] = recommendations.next_state(context['state'], JOB, chosen)
    context['recent'] = [dict(job_id=JOB['job_id'], request_text=JOB['request_text'], message='')]
    decision = handle(snapshot, group, context, '그걸로 찾아줘')
    assert [term.selection.term_id for term in decision.resolution.terms] == ['sit']


@pytest.mark.parametrize('text', ['2번이 좋아', '앉기가 좋겠어'])
def test_latest_user_focus_after_group_searches_immediately(snapshot_factory, card_factory, text):
    snapshot, group, context = setup(snapshot_factory, card_factory)
    focus_id = str(uuid4())
    recent = [dict(job_id=group.source_job_id, request_text='포즈 추천해줘', message=group.source_answer),
              dict(job_id=focus_id, request_text=text, message='좋아요.')]
    context['recent'] = recent
    memory = Memory(group)
    original = memory.records
    async def records(job, ids):
        return [recent[-1]] if ids == [focus_id] else await original(job, ids)
    memory.records = records
    decision = asyncio.run(recommendations.handle(memory, dict(JOB, request_text='그걸로 찾아줘'),
        InterpretationOutput(interpretation_state='drawing_chat', answer_text='좋아요.'), snapshot, context))
    assert [term.selection.term_id for term in decision.resolution.terms] == ['sit']


@pytest.mark.parametrize('message', ['', '앉기와 서기 모두 좋아요.'])
def test_unfocused_multi_candidate_pointer_still_asks(snapshot_factory, card_factory, message):
    snapshot, group, context = setup(snapshot_factory, card_factory)
    context['recent'] = [dict(job_id=group.source_job_id, request_text='포즈 추천해줘', message=message)]
    decision = handle(snapshot, group, context, '그걸로 찾아줘')
    assert decision.result.agent_status == 'needs_clarification'


@pytest.mark.parametrize('text', ['"2번으로 찾아줘"라는 문장을 설명해줘', '2번은 어떻게 그려?', '2번 말고 추천해줘'])
def test_quoted_or_howto_or_rejected_choice_is_not_focus(snapshot_factory, card_factory, text):
    snapshot, group, context = setup(snapshot_factory, card_factory)
    context['recent'] = [dict(job_id=group.source_job_id, request_text='포즈 추천해줘', message=group.source_answer),
        dict(job_id=str(uuid4()), request_text=text, message='')]
    decision = handle(snapshot, group, context, '그걸로 찾아줘')
    assert decision.result.agent_status == 'needs_clarification'


def test_adoption_from_previous_group_cannot_focus_new_group(snapshot_factory, card_factory):
    snapshot, group, context = setup(snapshot_factory, card_factory)
    chosen = handle(snapshot, group, context)
    context['state']['recommendation_adoption'] = chosen.adoption.model_dump(mode='json')
    context['state']['recommendation_adoption']['group_id'] = str(uuid4())
    context['recent'] = [dict(job_id=JOB['job_id'], request_text=JOB['request_text'], message='')]
    decision = handle(snapshot, group, context, '그걸로 찾아줘')
    assert decision.result.agent_status == 'needs_clarification'


def test_current_candidate_focus_never_bypasses_session_ownership(snapshot_factory, card_factory):
    snapshot, group, context = setup(snapshot_factory, card_factory)
    context['state']['recommendation_group']['session_id'] = str(uuid4())
    with pytest.raises(LLMInvalidStructuredOutput):
        handle(snapshot, group, context, '네가 골라서 찾아줘')


@pytest.mark.parametrize('text', ['그걸로 그리고 싶어', '그런 포즈 보고 싶어', '그걸로 찾아줘', '그걸로'])
def test_immediate_verified_suggestion_focuses_known_candidate(snapshot_factory, card_factory, text):
    snapshot, group, context = setup(snapshot_factory, card_factory)
    focus_id = str(uuid4())
    latest = dict(job_id=focus_id, request_text='어떤 후보가 좋아?', message='앉기를 추천해요.')
    context['recent'] = [dict(job_id=group.source_job_id, request_text='포즈 추천해줘', message=group.source_answer), latest]
    memory = Memory(group)
    original = memory.records
    async def records(job, ids):
        return [latest] if ids == [focus_id] else await original(job, ids)
    memory.records = records
    decision = asyncio.run(recommendations.handle(memory, dict(JOB, request_text=text),
        InterpretationOutput(interpretation_state='drawing_chat', answer_text='좋아요.'), snapshot, context))
    assert [term.selection.term_id for term in decision.resolution.terms] == ['sit']


@pytest.mark.parametrize('text', ['"2번으로 찾아줘"라는 문장을 설명해줘', '그걸로 어떻게 그려?',
    '"2번으로 찾아줘"는 예시야', '2번으로 그리는 법 알려줘', '2번으로 그리는 방법을 알려줘'])
def test_current_quoted_search_and_howto_never_adopt(snapshot_factory, card_factory, text):
    snapshot, group, context = setup(snapshot_factory, card_factory)
    decision = handle(snapshot, group, context, text)
    assert decision is None or decision.resolution is None


def test_quoted_recommendation_does_not_claim_current_recommendation_intent(snapshot_factory, card_factory):
    _, _, context = setup(snapshot_factory, card_factory)
    assert not recommendations.has_intent(dict(JOB, request_text='"추천해줘"는 예시 문장이야'), context)


def test_latest_unrelated_turn_stops_older_adoption_focus(snapshot_factory, card_factory):
    snapshot, group, context = setup(snapshot_factory, card_factory)
    chosen = handle(snapshot, group, context)
    context['state'] = recommendations.next_state(context['state'], JOB, chosen)
    context['recent'] = [dict(job_id=JOB['job_id'], request_text=JOB['request_text'], message=''),
        dict(job_id=str(uuid4()), request_text='새 주제 풍경 이야기하자', message='')]
    assert handle(snapshot, group, context, '그걸로 찾아줘').result.agent_status == 'needs_clarification'


@pytest.mark.parametrize('text', ['2번 설명 좀', '2번이 싫어', '2번이 좋아?', '1번과 2번이 좋아'])
def test_mention_without_unambiguous_current_choice_does_not_focus(snapshot_factory, card_factory, text):
    snapshot, group, context = setup(snapshot_factory, card_factory)
    context['recent'] = [dict(job_id=group.source_job_id, request_text='포즈 추천해줘', message=group.source_answer),
        dict(job_id=str(uuid4()), request_text=text, message='')]
    decision = handle(snapshot, group, context, '그걸로 찾아줘')
    assert decision.result.agent_status == 'needs_clarification'


def test_intervening_new_topic_breaks_old_group_focus(snapshot_factory, card_factory):
    snapshot, group, context = setup(snapshot_factory, card_factory)
    context['recent'] = [dict(job_id=group.source_job_id, request_text='포즈 추천해줘', message=group.source_answer),
        dict(job_id=str(uuid4()), request_text='새 주제로 바꿀게', message=''),
        dict(job_id=str(uuid4()), request_text='2번이 좋아', message='')]
    assert handle(snapshot, group, context, '그걸로 찾아줘').result.agent_status == 'needs_clarification'


def test_plain_search_without_focus_still_asks(snapshot_factory, card_factory):
    snapshot, group, context = setup(snapshot_factory, card_factory)
    assert handle(snapshot, group, context, '찾아줘').result.agent_status == 'needs_clarification'


@pytest.mark.parametrize('remove', [False, True])
def test_current_edits_and_removals_win_over_focused_candidate(snapshot_factory, card_factory, remove):
    candidate = dict(name='앉기', source_quote='앉기 하이앵글',
        terms=draft()['terms'] + [dict(role='composition', term_id='high', evidence=['하이앵글'], confidence=1)],
        unsupported_constraints=[])
    snapshot, group, context = setup(snapshot_factory, card_factory, [draft('서기', 'stand'), candidate])
    chosen = handle(snapshot, group, context)
    context['state'] = recommendations.next_state(context['state'], JOB, chosen)
    context['recent'] = [dict(job_id=JOB['job_id'], request_text=JOB['request_text'], message='')]
    kwargs = dict(context_updates=[dict(role='composition', term_id=None,
        evidence='하이앵글만 빼고', remove_term_ids=['high'])]) if remove else dict(selections=[
        dict(role='composition', term_id='low', evidence=['로우앵글'], confidence=1)])
    interpreted = InterpretationOutput(interpretation_state='select_terms', answer_text='조건을 바꿔요.', **kwargs)
    text = '그걸로 하이앵글만 빼고 찾아줘' if remove else '그걸로 로우앵글로 바꿔 찾아줘'
    decision = handle(snapshot, group, context, text, interpreted)
    assert [term.selection.term_id for term in decision.resolution.terms] == (['sit'] if remove else ['sit', 'low'])


def test_conflicting_current_name_and_ordinal_asks(snapshot_factory, card_factory):
    snapshot, group, context = setup(snapshot_factory, card_factory)
    decision = handle(snapshot, group, context, '1번 앉기로 찾아줘')
    assert decision.result.agent_status == 'needs_clarification'


def test_verified_latest_unstructured_suggestion_defers_to_normal_validation(snapshot_factory, card_factory):
    snapshot, _, _ = setup(snapshot_factory, card_factory)
    source = str(uuid4())
    latest = dict(job_id=source, request_text='포즈 아이디어가 필요해', message='서기를 추천해요.', terms=[])
    context = dict(state={}, recent=[latest], sources=[])
    class ScopedMemory:
        async def records(self, job, ids):
            assert list(map(str, ids)) == [source]
            return [latest]
    interpreted = InterpretationOutput(interpretation_state='select_terms', answer_text='서기로 찾아요.',
        selections=[dict(role='pose', term_id='stand', evidence=['서기'], confidence=1, source_job_id=source)])
    decision = asyncio.run(recommendations.handle(ScopedMemory(),
        dict(JOB, request_text='아까 추천한 그런 포즈로 찾아줘'), interpreted, snapshot, context))
    assert decision is None


@pytest.mark.parametrize('text, expected', [('1번 말고 2번으로 찾아줘', 'sit'),
    ('2번은 찾지 말고 1번 찾아줘', 'stand'), ('서기 말고 앉기로 찾아줘', 'sit')])
def test_explicit_later_candidate_correction_wins(snapshot_factory, card_factory, text, expected):
    snapshot, group, context = setup(snapshot_factory, card_factory)
    decision = handle(snapshot, group, context, text)
    assert [term.selection.term_id for term in decision.resolution.terms] == [expected]


def test_candidate_prohibition_alone_never_searches(snapshot_factory, card_factory):
    snapshot, group, context = setup(snapshot_factory, card_factory)
    decision = handle(snapshot, group, context, '2번 찾지 마')
    assert decision.resolution is None and decision.result.agent_status == 'drawing_chat'


@pytest.mark.parametrize('text', ['그걸로', '그걸로.'])
def test_bare_pointer_adopts_fresh_verified_user_focus(snapshot_factory, card_factory, text):
    snapshot, group, context = setup(snapshot_factory, card_factory)
    focus = dict(job_id=str(uuid4()), request_text='2번이 좋아', message='좋아요.')
    context['recent'] = [dict(job_id=group.source_job_id, request_text='포즈 추천해줘', message=group.source_answer), focus]
    memory = Memory(group)
    original = memory.records
    async def records(job, ids):
        return [focus] if ids == [focus['job_id']] else await original(job, ids)
    memory.records = records
    decision = asyncio.run(recommendations.handle(memory, dict(JOB, request_text=text),
        InterpretationOutput(interpretation_state='drawing_chat', answer_text='좋아요.'), snapshot, context))
    assert [term.selection.term_id for term in decision.resolution.terms] == ['sit']


def test_bare_pointer_without_focus_asks_minimal_question(snapshot_factory, card_factory):
    snapshot, group, context = setup(snapshot_factory, card_factory)
    assert handle(snapshot, group, context, '그걸로').result.agent_status == 'needs_clarification'


def test_bare_pointer_adopts_single_current_candidate(snapshot_factory, card_factory):
    snapshot, group, context = setup(snapshot_factory, card_factory, [draft()])
    assert [term.selection.term_id for term in handle(snapshot, group, context, '그걸로').resolution.terms] == ['sit']


@pytest.mark.parametrize('text', ['그거라는 단어는 뭐야', '그걸로 설명해줘', '"그걸로"는 예시야'])
def test_pointer_mention_alone_is_not_search_authorization(snapshot_factory, card_factory, text):
    snapshot, group, context = setup(snapshot_factory, card_factory)
    decision = handle(snapshot, group, context, text)
    assert decision is None or decision.resolution is None
