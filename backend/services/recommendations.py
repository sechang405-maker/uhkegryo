"""Bounded, session-owned recommendation evidence and explicit adoption.

Assistant prose is never passed wholesale to the search validator. Each proposal is
validated against its own original quote; only an explicitly adopted candidate can
contribute catalog terms. The source job is reread through the session-scoped store.
"""
from copy import deepcopy
from dataclasses import dataclass
import re
from uuid import NAMESPACE_URL, uuid5

from backend.schemas.enums import AgentStatus, InterpretationState, ReasonCode, Role
from backend.schemas.models import (AgentResult, InterpretationOutput, InterpretationSelection,
    RecommendationAdoption, RecommendationCandidate, RecommendationGroup)
from backend.services.llm import LLMInvalidStructuredOutput
from backend.services.resolver import ResolutionResult, resolve, STATUS_PROCEED
from backend.services.selection_grounding import has_affirmed_evidence
from backend.services.reference_intent import (current_action_text,
    search_forbidden as _search_forbidden, wants_reference)
from backend.services import session_memory


@dataclass
class Decision:
    interpretation: InterpretationOutput
    group: RecommendationGroup | None = None
    adoption: RecommendationAdoption | None = None
    resolution: ResolutionResult | None = None
    result: AgentResult | None = None


def invalid(code):
    return LLMInvalidStructuredOutput('Recommendation evidence could not be verified',
        stage='conversation_validation', feedback=[{'path': [], 'code': code}])


def search_forbidden(text):
    return _search_forbidden(text)


def wants_search(text):
    return wants_reference(text)


def one_shot(text):
    return recommends(text) and wants_search(text) and bool(re.search(
        r'추천(?:해서|하고|해\s*주고)|제안(?:해서|하고)|바로|\b(recommend\w*.*(?:then|and).*search|choose.*search)\b', text, re.I))


def recommends(text):
    return bool(re.search(r'추천|제안|\b(recommend\w*|suggest\w*)\b', text, re.I))


def generates_recommendations(text):
    if re.search(r'추천한|추천해\s*준|추천했|추천했던|\b(recommended|suggested)\b', text, re.I):
        return False
    return bool(re.search(r'추천(?:해|하|좀|\s*부탁)|제안(?:해|하)|\b(recommend|suggest)\b', text, re.I))


def _recall_prefix_end(text):
    """Past quoted actions remain recall data; a following clause can act now."""
    for clause in re.finditer(r'[^?？.!]+(?:[?？.!]|$)', text):
        value = clause.group()
        memory_question = re.search(r'기억(?:나|하니|해(?:요)?|하세요|하는지)|\b(remember|recall)\b', value, re.I)
        historical_question = (re.search(r'지난|아까|전에|이전|했던|했었|\b(earlier|previous|last)\b', value, re.I)
            and re.search(r'뭐|뭘|언제|무슨|어떤|했지|했니|했나|\b(what|when)\b', value, re.I))
        if memory_question or historical_question:
            return clause.end()
    return None


def _current_action_text(text):
    end = _recall_prefix_end(text)
    return current_action_text(text[end:].strip() if end is not None else text)


def reset_context(job, context):
    if session_memory.explicit_reset(job['request_text']):
        session_memory.clear_scope(context, str(job.get('job_id', '')))


def _apply_topic_evidence(job, interpretation, context):
    evidence = interpretation.topic_reset_evidence
    if evidence is None:
        return
    if (not evidence.strip() or evidence not in job['request_text']
            or not session_memory.reset_is_affirmed(job['request_text'], evidence)
            or not has_affirmed_evidence(evidence, [job['request_text']])
            or not re.search(r'주제|캐릭터|인물|동물|배경|풍경|그림|\b(subject|topic|character|animal|landscape)\b', evidence, re.I)):
        raise invalid('recommendation_topic_evidence_invalid')
    session_memory.clear_scope(context, str(job.get('job_id', '')))


def _group(context):
    stored = context['state'].get('recommendation_group')
    try:
        return RecommendationGroup.model_validate(stored) if stored else None
    except ValueError:
        raise invalid('recommendation_state_invalid') from None


def _delegates_choice(text):
    return wants_search(text) and bool(re.search(
        r'(?:네가|니가|너가|알아서|직접).{0,12}(?:골라|고르|선택)|좋은\s*(?:걸로|것으로)|'
        r'\b(?:you\s+(?:choose|pick)|choose\s+for\s+me|pick\s+(?:one|the best))\b', text, re.I))


def _candidate_mentions(text, group):
    ordinals = {int(value) for value in re.findall(r'(?<!\d)([1-9])\s*(?:번|번째|[.)])', text)}
    ordinals.update(int(value) for value in re.findall(r'\b(?:option|candidate|number)\s*([1-9])\b', text, re.I))
    names = {c.ordinal for c in group.candidates if c.name.casefold() in text.casefold()}
    return ordinals | names


def _bare_pointer(text):
    return bool(re.fullmatch(r'\s*그걸로[.!]?\s*', text))


async def _recent_focus(memory, job, group, context):
    """Resolve only a fresh focus, then reread its session-owned original."""
    recent = context.get('recent') or []
    if not recent:
        return 0
    latest = recent[-1]
    adoption = context['state'].get('recommendation_adoption') or {}
    if (adoption.get('group_id') == group.group_id and adoption.get('source_job_id') == group.source_job_id
            and adoption.get('adoption_job_id') == latest.get('job_id')):
        originals = await memory.records(job, [adoption['adoption_job_id']])
        original = next((row for row in originals if row['job_id'] == adoption['adoption_job_id']), {})
        if original.get('recommendation_adoption') != adoption:
            raise invalid('recommendation_focus_source_invalid')
        return next((c.ordinal for c in group.candidates if c.candidate_id == adoption.get('candidate_id')), 0)
    # A new group or an intervening unrelated turn cannot inherit an older choice.
    source_index = next((i for i, row in enumerate(recent) if row.get('job_id') == group.source_job_id), None)
    if source_index is None:
        return 0
    if any(re.search(r'새\s*주제|다른\s*주제|주제.{0,8}바[꾸꿀]|추천.{0,8}잊|\bnew topic\b',
            row.get('request_text', ''), re.I) for row in recent[source_index+1:]):
        return 0
    text = latest.get('request_text', '') if source_index < len(recent)-1 else ''
    # Quoted recalls, rejections and explanatory questions are not adoptions.
    if text and (_recall_prefix_end(text) is not None or search_forbidden(text)
            or re.search(r'["“”‘’]|말고|아니|제외|빼|어떻게|왜|설명|싫|별로|않|\b(?:not|except|how|why|explain)\b', text, re.I)):
        return 0
    if text:
        mentions = _candidate_mentions(text, group)
        if len(mentions) > 1:
            return 0
        if mentions and re.search(r'[?？]', text):
            return 0
        bare = bool(re.fullmatch(r'\s*[1-9]\s*(?:번|번째)?[.!]?\s*', text)) or any(
            text.strip().rstrip('.!') in (c.name, c.name+'요', c.name+'이요') for c in group.candidates)
        adopts = bare or wants_search(text) or bool(re.search(r'좋|할게|선택|고를|하자|마음|\b(?:use|choose|pick|prefer)\b', text, re.I))
        if len(mentions) == 1 and adopts:
            originals = await memory.records(job, [latest['job_id']])
            original = next((row for row in originals if row['job_id'] == latest['job_id']), {})
            if original.get('request_text') != text:
                raise invalid('recommendation_focus_source_invalid')
            return next(iter(mentions))
    # Suggestion prose identifies an existing option, never supplies new terms.
    relevant = source_index == len(recent)-1 or bool(re.search(
        r'추천|후보|어떤|어느|뭐가|\b(?:option|candidate|recommend|which)\b', text, re.I))
    if not relevant:
        return 0
    originals = await memory.records(job, [latest['job_id']])
    original = next((row for row in originals if row['job_id'] == latest['job_id']), {})
    if source_index < len(recent)-1 and original.get('request_text') != text:
        raise invalid('recommendation_focus_source_invalid')
    message = original.get('recommendation_answer') or original.get('message', '')
    choices = set()
    prose = '\n'.join(line for line in message.splitlines() if not re.match(r'\s*[1-9]\s*[.)번]', line))
    for clause in re.split(r'[.!?。！？\n]', prose):
        if (re.search(r'추천|좋겠|어울|권해|\b(?:recommend|suggest|choose|pick)\b', clause, re.I)
                and not re.search(r'말고|아니|제외|빼|\b(?:not|except)\b', clause, re.I)):
            mentions = _candidate_mentions(clause, group)
            choices.update(mentions)
    return next(iter(choices)) if len(choices) == 1 else 0


def _selection(text, group, context):
    """Return an ordinal, an ambiguity sentinel, or no recommendation intent."""
    if not group:
        return None
    text = _current_action_text(text)
    # An explicit replacement names the target in the affirmative later clause.
    # Keep the full original request for term/removal validation below.
    correction = re.split(r'말고', text)
    if (len(correction) > 1 and _candidate_mentions(' '.join(correction[:-1]), group)
            and wants_search(correction[-1]) and len(_candidate_mentions(correction[-1], group)) == 1):
        text = correction[-1].strip()
    if search_forbidden(text):
        return None
    if not wants_search(text) and re.search(r'왜|어떻게|이유|설명|그리는\s*(?:법|방법)|연습|배우|\b(why|how|explain|learn|practice)\b', text, re.I):
        return None
    normalized = text.casefold()
    ordinals = {int(value) for value in re.findall(r'(?<!\d)([1-9])\s*(?:번|번째|[.)])', normalized)}
    ordinals.update(int(value) for value in re.findall(r'\b(?:option|candidate|number)\s*([1-9])\b', normalized))
    names = {c.ordinal for c in group.candidates if c.name.casefold() in normalized}
    # A casual discussion about a suggestion does not authorize search.
    adopts = wants_search(text) or _bare_pointer(text) or bool(re.search(r'번(?:으로|인데|로)|\b(?:use|choose|pick|retry)\b|재시도', normalized))
    if not adopts:
        pending = context['state'].get('recommendation_pending_group_id') == group.group_id
        bare_ordinal = re.fullmatch(r'\s*([1-3])\s*(?:(?:번|번째)(?:이요|요|으로)?)?[.!]?\s*', text)
        bare = bool(bare_ordinal) or any(
            text.strip().rstrip('.!') in (c.name, c.name+'요', c.name+'이요') for c in group.candidates)
        if not pending or not bare:
            return None
        if bare_ordinal:
            ordinals.add(int(bare_ordinal[1]))
    if ordinals or names:
        if len(ordinals) == 1 and re.search(r'바꾸|바꿔|변경|추가|빼|\b(?:change|add|remove|replace)\b', text, re.I):
            return next(iter(ordinals))
        mentions = ordinals | names
        return next(iter(mentions)) if len(mentions) == 1 else 0
    if _delegates_choice(text):
        return group.candidates[0].ordinal
    if re.search(r'다시|재시도|\bretry\b', normalized):
        previous = context['state'].get('recommendation_adoption') or {}
        chosen = next((c.ordinal for c in group.candidates if c.candidate_id == previous.get('candidate_id')), None)
        if chosen:
            return chosen
    if re.search(r'추천|방금|그걸|그거|그런|그대로|\b(that|recommend\w*|suggest\w*)\b', normalized):
        return group.candidates[0].ordinal if len(group.candidates) == 1 else 0
    if wants_search(text) and re.fullmatch(r'\s*(?:찾아줘|검색해줘|find|search)[.!]?\s*', text, re.I):
        return group.candidates[0].ordinal if len(group.candidates) == 1 else 0
    if re.search(r'다시|재시도|\bretry\b', normalized):
        previous = context['state'].get('recommendation_adoption') or {}
        return next((c.ordinal for c in group.candidates if c.candidate_id == previous.get('candidate_id')), 0)
    return None


def has_intent(job, context):
    if _recall_prefix_end(job['request_text']) is not None:
        return False
    text = _current_action_text(job['request_text'])
    return (_selection(text, _group(context), context) is not None
            or generates_recommendations(text) or search_forbidden(text))


def _validated(terms, quote, snapshot, *, allow_disabled=False):
    if not terms:
        return []
    for term in terms:
        if term.source_job_id or any(not has_affirmed_evidence(phrase, [quote]) for phrase in term.evidence):
            raise invalid('recommendation_evidence_invalid')
        card = snapshot.get_active(term.term_id)
        if (not card or card.get('runtime_eligible') is False
                or card.get('mvp_status', 'active_in_current_contract') != 'active_in_current_contract'):
            raise invalid('recommendation_card_invalid')
    try:
        candidate = InterpretationOutput(interpretation_state='select_terms', answer_text='검증', selections=terms)
    except ValueError:
        raise invalid('recommendation_terms_invalid') from None
    resolution = resolve(candidate, snapshot, request_text=quote)
    if resolution.invalid_candidates:
        raise invalid('recommendation_card_invalid')
    disabled = {term.term_id for term in terms if snapshot.is_direct_search_disabled(term.term_id)}
    if (resolution.status != STATUS_PROCEED or len(resolution.terms) != len(terms)) and not (allow_disabled and disabled):
        raise invalid('recommendation_card_invalid')
    if {term.selection.term_id for term in resolution.terms} | (disabled if allow_disabled else set()) != {term.term_id for term in terms}:
        raise invalid('recommendation_card_invalid')
    return resolution.terms


def _condition_slot(role, term_id, snapshot):
    """Replace the stated catalog dimension, preserving independent same-role cards."""
    card = snapshot.get_active(term_id) or {}
    component = card.get('component', 'primary')
    if Role(role) == Role.COMPOSITION:
        if term_id in {'view_front','view_profile','view_back','view_three_quarter'}: component = 'orientation'
        elif term_id in {'view_high_angle','view_low_angle','view_birds_eye','view_worms_eye'}: component = 'elevation'
        elif term_id == 'view_dutch_angle': component = 'tilt'
        elif term_id.startswith(('composition_', 'layout_')): component = 'layout'
    elif Role(role) == Role.POSE and component == 'pose_variant':
        component = 'primary'
    elif component == 'modifier' or component not in {
            'primary','lower_body','support','hand_gesture','upper_body_gesture','prop_action','framing'}:
        component = term_id
    return Role(role), component


def create_group(job, interpretation, snapshot):
    if not interpretation.recommendation_candidates:
        return None
    group_id = str(uuid5(NAMESPACE_URL, f"recommendation:{job['session_id']}:{job['job_id']}"))
    blocks = list(re.finditer(r'(?m)^\s*([1-3])\s*[.)번]\s*', interpretation.answer_text))
    if [int(match[1]) for match in blocks] != list(range(1, len(interpretation.recommendation_candidates)+1)):
        raise invalid('recommendation_numbering_invalid')
    candidates = []
    for ordinal, draft in enumerate(interpretation.recommendation_candidates, 1):
        block = interpretation.answer_text[blocks[ordinal-1].end():blocks[ordinal].start() if ordinal < len(blocks) else len(interpretation.answer_text)]
        # A title and its evidence paragraph may be distinct spans in one option.
        # Only the verbatim quote authorizes terms; the name identifies the option.
        if draft.source_quote not in block or draft.name not in block:
            raise invalid('recommendation_quote_invalid')
        if any(value not in draft.source_quote for value in draft.unsupported_constraints):
            raise invalid('recommendation_unsupported_evidence_invalid')
        _validated(draft.terms, draft.source_quote, snapshot, allow_disabled=True)
        candidates.append(RecommendationCandidate(**draft.model_dump(), ordinal=ordinal,
            candidate_id=str(uuid5(NAMESPACE_URL, f'{group_id}:{ordinal}'))))
    return RecommendationGroup(group_id=group_id, source_job_id=str(job['job_id']),
        session_id=str(job['session_id']), source_answer=interpretation.answer_text, candidates=candidates)


async def _verify_group(memory, job, group):
    if group.session_id != str(job['session_id']):
        raise invalid('recommendation_owner_invalid')
    originals = await memory.records(job, [group.source_job_id])
    original = next((row for row in originals if row['job_id'] == group.source_job_id), None)
    if not original or original.get('recommendation_group') != group.model_dump(mode='json'):
        raise invalid('recommendation_source_invalid')
    answer = original.get('recommendation_answer', original.get('message', ''))
    if any(c.source_quote not in answer for c in group.candidates):
        raise invalid('recommendation_quote_invalid')


async def _retry_conditions(memory, job, candidate, context):
    """Restore the exact server-approved effective board, including user overrides."""
    stored = context['state'].get('recommendation_adoption') or {}
    if (not re.search(r'다시|재시도|\bretry\b', _current_action_text(job['request_text']), re.I)
            or stored.get('candidate_id') != candidate.candidate_id
            or not stored.get('search_term_ids') or not stored.get('adoption_job_id')):
        return candidate.terms, candidate.source_quote
    originals = await memory.records(job, [stored['adoption_job_id']])
    original = next((row for row in originals if row['job_id'] == stored['adoption_job_id']), None)
    if not original or original.get('recommendation_adoption') != stored:
        raise invalid('recommendation_retry_source_invalid')
    rows = original.get('terms', [])
    if {row['term_id'] for row in rows} != set(stored['search_term_ids']):
        raise invalid('recommendation_retry_conditions_invalid')
    terms = [InterpretationSelection(role=row['role'],term_id=row['term_id'],
        evidence=[row['label_ko']],confidence=1) for row in rows]
    return terms, '\n'.join(row['label_ko'] for row in rows)


def _blocked(decision, message):
    decision.adoption.status = 'blocked'
    decision.result = AgentResult(agent_status='reference_guidance', reason_codes=[ReasonCode.CATALOG_LIMITATION],
        user_message=message, recommendation_group=decision.group, recommendation_adoption=decision.adoption)
    return decision


async def handle(memory, job, interpretation, snapshot, context):
    _apply_topic_evidence(job, interpretation, context)
    active_text = _current_action_text(job['request_text'])
    if generates_recommendations(active_text) and not interpretation.recommendation_candidates:
        raise invalid('recommendation_candidates_missing')
    if search_forbidden(active_text) and not interpretation.recommendation_candidates:
        return Decision(interpretation=interpretation,result=AgentResult(agent_status='drawing_chat',
            answer_text=interpretation.answer_text or '아이디어를 더 구체적으로 이야기해볼게요.'))
    group = _group(context)
    immediate = one_shot(active_text)
    selected = None if immediate else _selection(job['request_text'], group, context)
    created = None
    if interpretation.recommendation_candidates:
        # A selected historical candidate is authoritative; a model cannot replace it.
        if selected is None:
            if recommends(active_text) and len(interpretation.recommendation_candidates) < 2:
                raise invalid('recommendation_candidate_count')
            created = create_group(job, interpretation, snapshot)
            group = created
            if wants_search(active_text) and recommends(active_text):
                selected = 1
            else:
                return Decision(interpretation=interpretation, group=group,
                    result=AgentResult(agent_status='drawing_chat', answer_text=interpretation.answer_text,
                        recommendation_group=group))
    if selected is None:
        if immediate and group:
            selected = group.candidates[0].ordinal
        elif not group and wants_search(active_text) and re.search(
                r'추천한|추천해\s*준|추천.{0,10}걸로|\b(recommended|suggested)\b', job['request_text'], re.I):
            # Nonstructured suggestions retain the normal narrower source validator.
            recent = context.get('recent') or []
            ids = list(dict.fromkeys(str(term.source_job_id) for term in interpretation.selections if term.source_job_id))
            if recent and ids == [str(recent[-1]['job_id'])]:
                from backend.services import conversation_context
                originals = await memory.records(job, ids)
                original = next((row for row in originals if str(row['job_id']) == ids[0]), None)
                if original and conversation_context.adopted_assistant_evidence(original, job, context):
                    resolution = await conversation_context.validate(memory, job, interpretation, snapshot, context=context)
                    if resolution.status == STATUS_PROCEED:
                        return None
            return Decision(interpretation=interpretation, result=AgentResult(agent_status='needs_clarification',
                reason_codes=[ReasonCode.INSUFFICIENT_VISUAL_EVIDENCE],
                clarifying_question='이전 추천을 안전하게 선택할 수 있도록 번호가 있는 후보를 먼저 추천해드릴까요?'))
        # Recommendation-only phrasing never runs image search even on a bad model route.
        elif recommends(active_text) and not wants_search(active_text):
            return Decision(interpretation=interpretation,
                result=AgentResult(agent_status='drawing_chat', answer_text=interpretation.answer_text or '원하는 그림의 주제를 알려주세요.'))
        else:
            return None
    if not created:
        await _verify_group(memory, job, group)
        if selected == 0 and (wants_search(active_text) or _bare_pointer(active_text)) and not _candidate_mentions(active_text, group):
            selected = await _recent_focus(memory, job, group, context)
    candidate = next((item for item in group.candidates if item.ordinal == selected), None)
    if candidate is None:
        return Decision(interpretation=interpretation, group=group,
            result=AgentResult(agent_status='needs_clarification', reason_codes=[ReasonCode.INSUFFICIENT_VISUAL_EVIDENCE],
                clarifying_question='어떤 후보로 찾을까요? ' + ', '.join(f'{c.ordinal}번 {c.name}' for c in group.candidates) + ' 중 번호나 이름을 골라주세요.',
                recommendation_group=group))
    adoption = RecommendationAdoption(group_id=group.group_id, source_job_id=group.source_job_id,
        candidate_id=candidate.candidate_id, adoption_job_id=str(job['job_id']),
        request_text=job['request_text'], source_quote=candidate.source_quote, status='searched')
    decision = Decision(interpretation=interpretation, group=group, adoption=adoption)
    if candidate.unsupported_constraints:
        return _blocked(decision, '선택한 추천의 ' + ', '.join(candidate.unsupported_constraints) +
            ' 조건은 현재 카탈로그로 검색할 수 없어요. 이 조건을 유지할 다른 후보나 대안을 알려주세요.')
    current = []
    for term in interpretation.selections:
        if term.source_job_id:
            # Historical assistant evidence is accepted only through the selected candidate.
            if (str(term.source_job_id) != group.source_job_id or term.term_id not in {t.term_id for t in candidate.terms}
                    or any(phrase not in candidate.source_quote for phrase in term.evidence)):
                raise invalid('recommendation_model_source_invalid')
            continue
        current.append(term)
    explicit = _validated(current, job['request_text'], snapshot)
    explicit_slots = {_condition_slot(term.selection.role, term.selection.term_id, snapshot) for term in explicit}
    confirmed = []
    constraints = context['state'].get('constraints', {})
    if constraints:
        from backend.services.conversation_memory import normalize_constraints
        constraints = normalize_constraints(constraints)
        constraints = {key:value for key,value in constraints.items()
            if _condition_slot(value['role'], key, snapshot) not in explicit_slots}
        ids = list(dict.fromkeys(item['source_job_id'] for item in constraints.values()))
        originals = await memory.records(job, ids) if ids else []
        by_id = {row['job_id']: row for row in originals}
        for item in constraints.values():
            original = by_id.get(str(item['source_job_id']))
            if not original or item['evidence'] not in original['request_text']:
                raise invalid('recommendation_confirmed_source_invalid')
            terms = [InterpretationSelection(role=item['role'], term_id=item['term_id'], evidence=[item['evidence']], confidence=1)]
            try:
                confirmed.extend(_validated(terms, original['request_text'], snapshot))
            except LLMInvalidStructuredOutput:
                return _blocked(decision, '이전에 확인한 조건을 현재 검색할 수 없어요. 대체할 조건을 알려주세요.')
    # Explicit removals are current-user evidence too; validate before applying them.
    if interpretation.context_updates:
        from backend.services import conversation_context
        check = InterpretationOutput(interpretation_state='select_terms', answer_text='검증',
            selections=current, context_updates=interpretation.context_updates)
        validation_context = deepcopy(context)
        validation_context['state']['constraints'] = {**validation_context['state'].get('constraints', {}),
            **{term.term_id:dict(role=term.role.value,term_id=term.term_id,evidence=candidate.source_quote,
                source_job_id=group.source_job_id) for term in candidate.terms}}
        await conversation_context.validate(memory, job, check, snapshot, context=validation_context,
            updates_only=not current)
    removed = {key for update in interpretation.context_updates for key in update.remove_term_ids}
    cleared = {update.role for update in interpretation.context_updates if update.term_id is None and not update.remove_term_ids}
    confirmed = [term for term in confirmed if _condition_slot(term.selection.role,term.selection.term_id,snapshot) not in explicit_slots and term.selection.term_id not in removed
        and term.selection.role not in cleared]
    occupied = explicit_slots | {_condition_slot(term.selection.role,term.selection.term_id,snapshot) for term in confirmed}
    base_terms, base_quote = await _retry_conditions(memory, job, candidate, context)
    candidate_terms = [term for term in base_terms if _condition_slot(term.role,term.term_id,snapshot) not in occupied
        and term.role not in cleared and term.term_id not in removed]
    try:
        supplements = _validated(candidate_terms, base_quote, snapshot)
    except LLMInvalidStructuredOutput:
        return _blocked(decision, '선택한 추천에 현재 검색할 수 없는 조건이 있어요. 다른 후보나 대안을 골라주세요.')
    selected_terms = [*explicit, *confirmed, *supplements]
    selected_terms = [term for role in Role for term in selected_terms if term.selection.role == role]
    if not selected_terms or len(selected_terms) > 10:
        return _blocked(decision, '선택한 후보에서 검색할 조건을 확정할 수 없어요. 사용할 조건을 알려주세요.')
    actual = ', '.join(term.card['label_ko'] for term in selected_terms)
    decision.interpretation = InterpretationOutput(interpretation_state='select_terms',
        answer_text=f'추천한 ‘{candidate.name}’을 선택하고 {actual} 조건으로 찾아볼게요.',
        selections=[term.selection.model_copy(update={'source_job_id':None}) for term in selected_terms],
        context_updates=interpretation.context_updates)
    adoption.search_term_ids = [term.selection.term_id for term in selected_terms]
    decision.resolution = ResolutionResult(status=STATUS_PROCEED, terms=selected_terms,
        unresolved_roles=[role for role in Role if role not in {term.selection.role for term in selected_terms}])
    return decision


def finish(result, decision):
    if decision is None:
        return result
    result.recommendation_group = decision.group
    result.recommendation_adoption = decision.adoption
    if decision.adoption and result.agent_status == AgentStatus.PARTIAL_RESULT:
        decision.adoption.status = 'search_failed'
        result.answer_text = '선택한 후보의 조건으로 검색했지만 일부 자료를 찾지 못했어요. 같은 후보로 다시 찾으려면 재시도를 요청해주세요.'
    return result


def next_state(state, job, decision):
    state = deepcopy(state)
    if decision and decision.group:
        if not state.get('topic_scope_id'):
            state['topic_scope_id'] = str(job['job_id'])
        state['recommendation_topic_scope'] = state.get('topic_scope_id')
        state['recommendation_group'] = decision.group.model_dump(mode='json')
        state['recommendation_adoption'] = decision.adoption.model_dump(mode='json') if decision.adoption else None
        state['recommendation_pending_group_id'] = decision.group.group_id if (
            decision.result and decision.result.agent_status == AgentStatus.NEEDS_CLARIFICATION) else None
    elif wants_search(job['request_text']) and not has_intent(job, {'state':state}):
        state['recommendation_group'] = None
        state['recommendation_adoption'] = None
        state['recommendation_pending_group_id'] = None
    return state
