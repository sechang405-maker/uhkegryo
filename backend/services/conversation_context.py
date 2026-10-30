"""Bounded context, original-source validation, and recall orchestration."""
import re
from copy import deepcopy

from backend.schemas.enums import AgentStatus, ReasonCode, Role
from backend.services.clarification_policy import repeated_question, REPEATED_FALLBACK
from backend.schemas.models import AgentResult, InterpretationOutput, InterpretationSelection
from backend.schemas.memory import RecallQuery, RecallAnswer, MemorySource, NO_RECORDS, TOO_MANY
from backend.services.conversation_memory import evidence_text, normalize_constraints, RECENT_LIMIT
from backend.services.llm import LLMInvalidStructuredOutput
from backend.services.reference_intent import wants_reference, current_action_text
from backend.services import session_memory
from backend.services.selection_grounding import has_affirmed_evidence
from backend.services.resolver import resolve, ResolutionResult, STATUS_CLARIFY, STATUS_ALL_INVALID, STATUS_PROCEED

# Narrow literal alternatives for existing catalog concepts, never a default or
# semantic mapping from mood, props, or an unspecified character to a card.
_REFERENCE_ALIASES = session_memory.REFERENCE_ALIASES

async def prepare(memory, job, adapter, trace):
    context = await memory.load(job)
    if context.get("previous_result"):
        context["previous_result"] = AgentResult.model_validate(context["previous_result"]).model_dump(mode="json")
    return context


def prompt_context(context):
    state = context["state"]
    def prompt_record(row):
        return {key:value for key,value in row.items() if key not in ('recommendation_group','recommendation_answer','recommendation_adoption')}
    sources = []
    recent = [prompt_record(row) for row in context['recent']]
    seen = list(recent)
    for original in context["sources"]:
        source = prompt_record(original)
        job_id = source.get("job_id")
        if job_id is not None and any(row.get("job_id") == job_id and row == source for row in seen):
            continue
        sources.append(source)
        seen.append(source)
    output = {"constraints": normalize_constraints(state.get("constraints", {})), "pending_question": state.get("pending_question"),
            "recent": recent, "sources": sources}
    for key in ('current_topic', 'excluded_conditions', 'topic_scope_id', 'recommendation_topic_scope'):
        if key in state:
            output[key] = state[key]
    for key in ('recommendation_group', 'recommendation_adoption'):
        if state.get(key):
            output[key] = ({field:value for field,value in state[key].items() if field != 'source_answer'}
                if key == 'recommendation_group' else state[key])
    return output


def trace_args(job):
    return {key: str(job[key]) if key in ("job_id", "session_id") else job[key]
            for key in ("job_id", "session_id", "attempt", "max_attempts")}


async def recall(memory, job, context, adapter, trace, query: RecallQuery | None = None):
    if query is None and is_clear_new_request(job["request_text"], context):
        return None, False
    with trace.stage("memory-recall"):
        if query is None:
            query = await adapter.memory("classify", {
                "request_text": job["request_text"], "session_context": prompt_context(context),
                "current_reference_terms": [{key: term[key] for key in ("role", "term_id", "label_ko", "label_en")} for term in
                    ((context.get("previous_result") or {}).get("reference_plan") or {}).get("terms", [])],
                "current_reference_roles": [term["role"] for term in
                    ((context.get("previous_result") or {}).get("reference_plan") or {}).get("terms", [])],
            }, RecallQuery, **trace_args(job))
        if query.mode == 'recall' and wants_reference(job['request_text']):
            context['reference_action'] = 'update'
            return None, False
        context["reference_action"] = query.reference_action if query.mode != "recall" else "update"
        context["refresh_roles"] = query.refresh_roles if query.mode != "recall" else []
        context["refresh_term_ids"] = query.refresh_term_ids if query.mode != "recall" else []
        if query.mode == "none":
            return None, False
        records = await memory.search(job, query)
        if not records or len(records) > 20:
            return AgentResult(agent_status=AgentStatus.MEMORY_ANSWER,
                               memory_answer=NO_RECORDS if not records else TOO_MANY), query.mode == "recall"
        answer = await adapter.memory("answer", {
            "request_text": job["request_text"], "records": records,
        }, RecallAnswer, **trace_args(job))
        by_id = {item["job_id"]: item for item in records}
        sources = {}
        for citation in answer.citations:
            job_id = str(citation.job_id)
            if job_id not in by_id or not citation.quote.strip() or citation.quote not in evidence_text(by_id[job_id]):
                raise LLMInvalidStructuredOutput("회상 답변의 원본 인용을 확인할 수 없습니다", stage="conversation_validation",
                                                 feedback=[{"path": [], "code": "recall_citation_invalid"}])
            sources[job_id] = MemorySource(job_id=job_id, href="/api/jobs/" + job_id)
        context["sources"] += records
        return AgentResult(agent_status=AgentStatus.MEMORY_ANSWER, memory_answer=answer.answer,
                           sources=list(sources.values())), query.mode == "recall"


def is_clear_new_request(text, context):
    text = text.casefold().strip()
    if re.search(r"새|다른|\b(new|different|refresh)\b", text) and (
            context.get("previous_result") or re.search(r"이미지|레퍼런스|참고|\b(image|reference)\b", text)):
        return False
    if context["state"].get("pending_question") or len(text) < 12:
        return False
    historical = ("아까|이전|전에|지난|그때|방금|추천|기억|했|였|뭐|무엇|어떤|그거|그것|똑같|"
                  "같은|다시|그대로|유지|바꿔|변경|말해|알려|앞서|저번|마지막|첫|결과|사용한|보낸|선택한|[?？]|"
                  r"(^|\s)(이|그|저|해당)\s|\b(first|previous|earlier|remember|recommend\w*|suggest\w*|again|that|what|change|same|history)\b")
    if re.search(historical, text):
        return False
    return bool(re.search(r"체형|자세|포즈|시점|원근|투시|앵글|구도|배치|캐릭터|레퍼런스|\b(reference|pose|character|perspective)\b", text)
                and re.search(r"찾아|그려|그리(?:고|려|기|는|면|자|거나|다가)|그릴|그린|보여|검색|설명|\b(find|draw|show|search|explain)\b", text))


async def validate(memory, job, interpretation, snapshot, *, context=None, updates_only=False):
    ids = list(dict.fromkeys(item.source_job_id for item in interpretation.selections if item.source_job_id))
    originals = await memory.records(job, ids) if ids else []
    by_id = {item["job_id"]: item for item in originals}
    verified_source_texts = {}
    for selection in interpretation.selections:
        if selection.source_job_id:
            state = (context or {}).get('state', {})
            if state.get('topic_scope_id'):
                scoped_ids = {str(row.get('job_id')) for row in
                    [*(context or {}).get('recent', []), *(context or {}).get('sources', [])]}
                scoped_ids.update(map(str, session_memory.source_ids(state)))
                scoped_ids.update(str(value['source_job_id']) for value in state.get('constraints', {}).values() if value.get('source_job_id'))
                if str(selection.source_job_id) not in scoped_ids:
                    raise LLMInvalidStructuredOutput('Source is outside the current topic scope',
                        stage='conversation_validation', feedback=[{'path': [], 'code': 'selection_source_invalid'}])
            if selection.term_id in ((context or {}).get('state', {}).get('excluded_conditions') or {}):
                raise LLMInvalidStructuredOutput('Excluded conditions require fresh current-user evidence',
                    stage='conversation_validation', feedback=[{'path': [], 'code': 'selection_evidence_invalid'}])
            if (context or {}).get('_recommendation_topic_reset') or interpretation.topic_reset_evidence:
                raise LLMInvalidStructuredOutput('Prior-topic sources cannot support a new topic',
                    stage='conversation_validation', feedback=[{'path': [], 'code': 'selection_source_invalid'}])
            original = by_id.get(str(selection.source_job_id))
            if original is None:
                raise LLMInvalidStructuredOutput("선택 출처가 검증된 선행 기록에 없습니다", stage="conversation_validation",
                                                 feedback=[{"path": [], "code": "selection_source_invalid"}])
            allowed = [original["request_text"]] + [t[k] for t in original["terms"] for k in ("label_ko", "label_en")]
            allowed += adopted_assistant_evidence(original, job, context or {})
            condition = normalize_constraints((context or {}).get('state', {}).get('constraints', {})).get(selection.term_id)
            if (condition and condition['role'] == selection.role.value
                    and str(condition.get('source_job_id')) == str(selection.source_job_id)
                    and condition.get('evidence')
                    and condition['evidence'] in (original.get('message') or '')):
                allowed.append(condition['evidence'])
            recent = (context or {}).get('recent') or []
            source_index = next((index for index, row in enumerate(recent)
                if str(row.get('job_id')) == str(selection.source_job_id)), -1)
            newer = [row.get('request_text', '') for row in recent[source_index + 1:]] + [job['request_text']]
            removed = {term_id for update in interpretation.context_updates for term_id in update.remove_term_ids}
            cleared = {update.role for update in interpretation.context_updates
                if update.term_id is None and not update.remove_term_ids}
            if (selection.term_id in removed or selection.role in cleared
                    or any(explicitly_excluded(text, phrase) for text in newer for phrase in selection.evidence)):
                raise LLMInvalidStructuredOutput('Removed conditions cannot be restored from old evidence',
                    stage='conversation_validation', feedback=[{'path': [], 'code': 'selection_evidence_invalid'}])
        else:
            allowed = [job["request_text"]]
        if any(not any(phrase in text for text in allowed) for phrase in selection.evidence):
            raise LLMInvalidStructuredOutput("선택 근거가 실제 요청 또는 원본 카드 라벨에 없습니다", stage="conversation_validation",
                                             feedback=[{"path": [], "code": "selection_evidence_invalid"}])
        if selection.source_job_id:
            verified_source_texts[str(selection.source_job_id)] = tuple(allowed)
    known = {term['term_id']: Role(term['role']).value for term in
             (((context or {}).get('previous_result') or {}).get('reference_plan') or {}).get('terms', [])}
    known.update({key: value['role'] for key, value in normalize_constraints(
        (context or {}).get('state', {}).get('constraints', {})).items()})
    known.update({term['term_id']: Role(term['role']).value for term in
        (((context or {}).get('state', {}).get('current_topic') or {}).get('terms', []))})
    resulting = dict(known)
    seen = set()
    for update in interpretation.context_updates:
        if any(known.get(term_id) != update.role.value for term_id in update.remove_term_ids):
            raise LLMInvalidStructuredOutput('Removal must identify an existing card of the same role',
                stage='conversation_validation', feedback=[{'path': [], 'code': 'context_removal_invalid'}])
        for term_id in update.remove_term_ids:
            resulting.pop(term_id, None)
        if update.term_id is None and not update.remove_term_ids:
            resulting = {key: role for key, role in resulting.items() if role != update.role.value}
        elif update.term_id is not None:
            resulting[update.term_id] = update.role.value
        identity = (update.role, update.term_id, tuple(update.remove_term_ids))
        if identity in seen or not update.evidence.strip() or update.evidence not in job["request_text"]:
            raise LLMInvalidStructuredOutput("조건 변경에 현재 요청의 명시적 근거가 필요합니다", stage="conversation_validation",
                                             feedback=[{"path": [], "code": "context_evidence_invalid"}])
        seen.add(identity)
        if update.term_id is not None:
            # This internal candidate only checks the catalog; its text is never returned as an answer.
            candidate = InterpretationOutput(interpretation_state="select_terms", answer_text=update.evidence, selections=[
                InterpretationSelection(role=update.role, term_id=update.term_id,
                                        evidence=[update.evidence], confidence=1)])
            if resolve(candidate, snapshot, request_text=str(job["request_text"])).status == STATUS_ALL_INVALID:
                raise LLMInvalidStructuredOutput("기억할 조건의 카드가 유효하지 않습니다", stage="conversation_validation",
                                                 feedback=[{"path": [], "code": "context_card_invalid"}])
    resulting.update({item.term_id: item.role.value for item in interpretation.selections})
    if updates_only:
        if interpretation.selections or not interpretation.context_updates or any(
                update.term_id is not None for update in interpretation.context_updates):
            raise LLMInvalidStructuredOutput('Update-only validation requires explicit removals',
                stage='conversation_validation', feedback=[{'path': [], 'code': 'context_removal_invalid'}])
        return None
    if len(resulting) > 10:
        raise LLMInvalidStructuredOutput('Conversation cannot contain more than ten cards',
            stage='conversation_validation', feedback=[{'path': [], 'code': 'context_card_limit'}])
    if (not interpretation.selections and interpretation.context_updates
            and interpretation.interpretation_state.value == 'select_terms'
            and all(update.term_id is None for update in interpretation.context_updates)):
        return ResolutionResult(status=STATUS_PROCEED, terms=[], unresolved_roles=list(Role))
    resolution = resolve(interpretation, snapshot, request_text=str(job["request_text"]),
                         verified_source_texts=verified_source_texts)
    if resolution.status == STATUS_CLARIFY and repeated_question(resolution.clarifying_question, context):
        return ResolutionResult(status='guidance', reason_codes=[ReasonCode.CLARIFICATION_REPEATED],
                                user_message=REPEATED_FALLBACK)
    if resolution.status == STATUS_ALL_INVALID or resolution.invalid_candidates:
        raise LLMInvalidStructuredOutput("선택 카드가 현재 카탈로그에서 유효하지 않습니다", stage="conversation_validation",
                                         feedback=[{"path": [], "code": "selection_card_invalid"}])
    if resolution.status == STATUS_PROCEED and (
            {item.term_id for item in interpretation.selections}
            != {item.selection.term_id for item in resolution.terms}):
        raise LLMInvalidStructuredOutput("일부 선택이 제외되어 통합 설명을 그대로 사용할 수 없습니다", stage="conversation_validation",
                                         feedback=[{"path": [], "code": "selection_card_invalid"}])
    return resolution


def explicitly_excluded(text, phrase):
    for match in re.finditer(re.escape(phrase), text):
        suffix = re.sub(r'^\s*(?:건|것은|것이|게|조건은|은|는|을|를)?\s*', '', text[match.end():])
        if re.match(r'(?:빼|제외하|삭제하)(?:지|지는)\s*말', suffix):
            continue
        if re.match(r'빼|제외|삭제|아니|말고|대신', suffix):
            return True
    return False


def adopted_assistant_evidence(original, job, context):
    """Authorize only the latest suggestion explicitly adopted by this request.

    The caller has reread the original through the session-scoped records store.
    Structured recommendation candidates have their own narrower adoption path.
    """
    recent = context.get('recent') or []
    text = current_action_text(job['request_text'])
    if (not recent or str(recent[-1].get('job_id')) != str(original['job_id'])
            or original.get('recommendation_group') or not wants_reference(text)
            or not re.search(r'그런|그걸로|그거|추천한\s*걸로|그\s*(?:포즈|자세|설명|제안|조건)|그대로|말한\s*대로|'
                             r'\b(?:that|your suggestion|as suggested)\b', text, re.I)):
        return []
    return [clause for clause in re.split(r'[.!?。！？\n]', original.get('message') or '')
            if re.search(r'어때|추천|제안|해\s*보|좋겠|\b(?:suggest|recommend|try)\b', clause, re.I)
            and not re.search(r'않|아니|말고|제외|\b(?:not|never|avoid)\b', clause, re.I)]


def related_reference_record(recent):
    """Skip only clarification-only pointer turns; preserve substantive replies.

    This recovers a clarification retry without searching wider history or crossing
    a fresh subject/removal. Source content is still reread from the session store.
    """
    for row in reversed(recent[-RECENT_LIMIT:]):
        pointer_only = re.fullmatch(
            r'\s*(?:(?:이런|그런)\s*(?:캐릭터|포즈|자세)(?:를|을)?\s*'
            r'(?:그리고|그려\s*보고|보고)\s*싶(?:어|어요|습니다)|'
            r'(?:그걸로|그거|그대로)?\s*(?:찾아\s*(?:줘|주세요)|검색\s*해\s*(?:줘|주세요)))'
            r'[.!?\s]*', row.get('request_text', ''))
        bare_desire = re.fullmatch(
            r'\s*(?:\uadf8\ub9ac\uace0|\uadf8\ub824\s*\ubcf4\uace0)\s*'
            r'\uc2f6(?:\uc5b4|\uc5b4\uc694|\ub2e4|\uc2b5\ub2c8\ub2e4)[.!?\s]*',
            row.get('request_text', ''))
        if (not row.get('terms') and (pointer_only or bare_desire) and row.get('question')
                and not (row.get('message') or '').strip()):
            continue
        return row
    return None


async def reference_fallback(memory, job, interpretation, snapshot, context):
    """Repair only a clear reference request misrouted to chat/missing-detail.

    Exact current catalog labels and already grounded user conditions are safe
    candidates. This is deliberately not a semantic synonym or scene generator.
    """
    from backend.schemas.enums import InterpretationState, ClarificationType
    from backend.schemas.memory import ContextUpdate
    from backend.services.recommendations import _condition_slot
    text = job['request_text']
    editing = interpretation.interpretation_state is InterpretationState.SELECT_TERMS
    if ((not wants_reference(text) and not editing)
            or interpretation.interpretation_state not in (
                InterpretationState.DRAWING_CHAT, InterpretationState.NEEDS_CLARIFICATION, InterpretationState.SELECT_TERMS)
            or interpretation.clarification_type in (
                ClarificationType.CONFLICTING_CONSTRAINTS, ClarificationType.CATALOG_LIMITATION)):
        return interpretation
    updates = list(interpretation.context_updates)
    removed = {term_id for update in updates for term_id in update.remove_term_ids}
    cleared = {update.role.value for update in updates if update.term_id is None and not update.remove_term_ids}
    current = current_action_text(text)
    selections = {item.term_id: item for item in interpretation.selections}
    def labels(source, source_id=None):
        for term_id, match in session_memory.literal_terms(source, snapshot, _REFERENCE_ALIASES).items():
            card = snapshot.active_cards[term_id]
            if editing and card['role'] not in {item.role.value for item in interpretation.selections}:
                continue
            if (term_id in removed or card['role'] in cleared or card.get('component') == 'composite'
                    or snapshot.is_direct_search_disabled(term_id)):
                continue
            for label in (match['evidence'],):
                if explicitly_excluded(source, label):
                    continue
                if len(label.strip()) > 1 and label in source and has_affirmed_evidence(label, [source]):
                    selections[term_id] = InterpretationSelection(role=card['role'], term_id=term_id,
                        evidence=[label], confidence=1, source_job_id=source_id)
                    break
    labels(current)
    topic = context.get('state', {}).get('current_topic') or {}
    topic_terms = {item['term_id']: item for item in topic.get('terms', [])}
    # A generic pointer ("그런 구도로") cannot supersede the specific topic.
    contextual = list(topic_terms.values()) + list(normalize_constraints(context.get('state', {}).get('constraints', {})).values())
    specific = [InterpretationSelection(role=item['role'],term_id=item['term_id'],
        evidence=[item['evidence']],confidence=1,source_job_id=item['source_job_id']) for item in contextual
        if snapshot.get_active(item['term_id']) and item.get('source_job_id') and item.get('evidence')]
    surviving = {item.term_id for item in session_memory.prune_nested([*selections.values(), *specific], snapshot)}
    selections = {key:value for key,value in selections.items() if key in surviving}
    current_selections = dict(selections)
    current_slots = {_condition_slot(item.role, item.term_id, snapshot) for item in current_selections.values()}
    reset = context.get('_recommendation_topic_reset') or interpretation.topic_reset_evidence
    pointer = re.search(r'이런|그런|그걸로|그거|추천한\s*걸로|그대로|그\s*(?:포즈|자세|캐릭터|조건|설명)|바꿔|유지|'
                        r'\b(?:that|same|keep|change)\b', current, re.I)
    pointer = pointer or re.fullmatch(r'\s*(?:찾아\s*(?:줘|주세요)|검색\s*해\s*(?:줘|주세요)|'
        r'(?:please\s+)?(?:find|search)(?:\s+(?:it|references?))?)[.!?\s]*', current, re.I)
    constraints = normalize_constraints(context.get('state', {}).get('constraints', {}))
    pointer = pointer or re.fullmatch(r'\s*(?:그리고|그려\s*보고)\s*싶(?:어|어요|다|습니다)[.!?\s]*', current) or editing
    excluded = context.get('state', {}).get('excluded_conditions') or {}
    if pointer and not reset:
        ids = list(dict.fromkeys(value['source_job_id'] for value in constraints.values() if value.get('source_job_id')))
        ids = list(dict.fromkeys([*ids, *session_memory.source_ids(context.get('state', {}))]))
        recent = context.get('recent') or []
        related = related_reference_record(recent)
        # At most one bounded related user source; never search older DB history.
        if not ids and related and not editing:
            ids = [related['job_id']]
        originals = await memory.records(job, ids) if ids else []
        by_id = {str(row['job_id']): row for row in originals}
        for term_id, condition in {**topic_terms, **constraints}.items():
            if not condition.get('source_job_id'):
                continue
            original = by_id.get(str(condition['source_job_id']))
            card = snapshot.get_active(term_id)
            evidence = condition.get('evidence', '')
            if (not original or not card or term_id in removed or term_id in excluded or card['role'] in cleared
                    or _condition_slot(card['role'], term_id, snapshot) in current_slots
                    or snapshot.is_direct_search_disabled(term_id)
                    or explicitly_excluded(current, evidence)
                    or (evidence in current and not has_affirmed_evidence(evidence, [current]))):
                continue
            allowed = [original['request_text']] + [term[k] for term in original['terms']
                for k in ('label_ko', 'label_en')]
            if evidence and evidence in (original.get('message') or ''):
                allowed.append(evidence)
            if has_affirmed_evidence(evidence, [value.casefold() for value in allowed]):
                selections.setdefault(term_id, InterpretationSelection(role=card['role'], term_id=term_id,
                    evidence=[evidence], confidence=1, source_job_id=condition['source_job_id']))
        if not constraints and not topic_terms and related:
            original = by_id.get(str(related['job_id']))
            if original:
                # Replace only the stated dimension, retaining independent framing.
                before = dict(selections)
                source_text = re.sub(r'"[^"\n]*"|“[^”\n]*”|‘[^’\n]*’|(?<!\w)\'[^\'\n]*\'', ' ', original['request_text'])
                labels(source_text, original['job_id'])
                for suggestion in adopted_assistant_evidence(original, job, context):
                    labels(suggestion, original['job_id'])
                selections = {key: value for key, value in selections.items()
                    if value.source_job_id is None
                    or _condition_slot(value.role, value.term_id, snapshot) not in current_slots}
                selections.update(before)
    selections = {item.term_id:item for item in session_memory.prune_nested(list(selections.values()), snapshot)
        if item.term_id not in excluded or item.source_job_id is None}
    # Merge preservation also needs explicit removal of superseded known cards.
    # Do not invent prior IDs when only immediate dialogue exists without a board.
    known = {term['term_id']: term['role'] for term in
        ((context.get('previous_result') or {}).get('reference_plan') or {}).get('terms', [])}
    known.update({term_id: value['role'] for term_id, value in constraints.items()})
    for item in current_selections.values():
        if editing and any(update.role == item.role and (update.remove_term_ids or update.term_id is None)
                           for update in interpretation.context_updates):
            continue
        slot = _condition_slot(item.role, item.term_id, snapshot)
        superseded = [term_id for term_id, role in known.items() if term_id != item.term_id
            and term_id not in removed and _condition_slot(role, term_id, snapshot) == slot]
        if superseded:
            updates.append(ContextUpdate(role=item.role, evidence=item.evidence[0], remove_term_ids=superseded))
    if not selections:
        if interpretation.interpretation_state is InterpretationState.DRAWING_CHAT:
            return InterpretationOutput(interpretation_state='needs_clarification',
                clarification_type='insufficient_visual_evidence', unresolved_constraints=['검색할 자세나 방향'],
                clarifying_question='찾을 캐릭터의 자세나 보는 방향을 한 가지만 알려주시겠어요?')
        return interpretation
    if len(selections) > 10:
        return interpretation
    labels_text = ', '.join(snapshot.get_active(term_id)['label_ko'] for term_id in selections)
    explanation = interpretation.answer_text if editing else f'말씀하신 조건 중 {labels_text} 기준으로 참고 자료를 찾았어요.'
    if interpretation.unresolved_constraints:
        explanation += ' 아직 확정되지 않은 조건은 검색에 추가하지 않았어요.'
    candidate = InterpretationOutput(interpretation_state='select_terms',
        answer_text=explanation,
        selections=sorted(selections.values(), key=lambda item: list(Role).index(item.role)), context_updates=updates,
        topic_reset_evidence=interpretation.topic_reset_evidence)
    resolution = await validate(memory, job, candidate, snapshot, context=context)
    return candidate if resolution.status == STATUS_PROCEED else interpretation


def next_state(context, job, interpretation, result, *, snapshot=None):
    state = deepcopy(context["state"])
    if snapshot is not None and result.agent_status in (AgentStatus.DRAWING_CHAT, AgentStatus.SUCCESS,
            AgentStatus.PARTIAL_RESULT, AgentStatus.NEEDS_CLARIFICATION, AgentStatus.REFERENCE_GUIDANCE):
        state = session_memory.observe(state, job, snapshot)
    if result.agent_status is AgentStatus.REFERENCE_GUIDANCE:
        state['pending_question'] = None
        return state
    if result.agent_status not in (AgentStatus.SUCCESS, AgentStatus.PARTIAL_RESULT, AgentStatus.NEEDS_CLARIFICATION):
        return state
    if result.agent_status is AgentStatus.NEEDS_CLARIFICATION:
        state['pending_question'] = result.clarifying_question
        return state
    constraints = normalize_constraints(state.get("constraints", {}))
    topic = deepcopy(state.get('current_topic'))
    topic_terms = list((topic or {}).get('terms', []))
    for update in interpretation.context_updates if result.agent_status is not AgentStatus.NEEDS_CLARIFICATION else []:
        topic_removals = set(update.remove_term_ids)
        if update.term_id is None and not update.remove_term_ids:
            topic_removals.update(term['term_id'] for term in topic_terms
                                  if term['role'] == update.role.value)
        for term in topic_terms:
            if term['term_id'] in topic_removals:
                state.setdefault('excluded_conditions', {})[term['term_id']] = dict(
                    role=term['role'], term_id=term['term_id'], evidence=update.evidence,
                    source_job_id=str(job['job_id']))
        topic_terms = [term for term in topic_terms if term['term_id'] not in topic_removals]
        for term_id in update.remove_term_ids:
            state.setdefault('excluded_conditions', {})[term_id] = dict(role=update.role.value,
                term_id=term_id, evidence=update.evidence, source_job_id=str(job['job_id']))
            constraints.pop(term_id, None)
        if update.term_id is None and not update.remove_term_ids:
            for term_id, condition in constraints.items():
                if condition['role'] == update.role.value:
                    state.setdefault('excluded_conditions', {})[term_id] = dict(role=update.role.value,
                        term_id=term_id, evidence=update.evidence, source_job_id=str(job['job_id']))
            constraints = {key: value for key, value in constraints.items() if value["role"] != update.role.value}
        elif update.term_id is not None:
            constraints[update.term_id] = {"role": update.role.value, "term_id": update.term_id,
                "evidence": update.evidence, "source_job_id": str(job["job_id"])}
    if topic is not None:
        if topic_terms:
            topic['terms'] = topic_terms
            state['current_topic'] = topic
        else:
            state['current_topic'] = None
    final_ids = {term.term_id for term in result.reference_plan.terms} if result.reference_plan else set()
    removed = {term_id for update in interpretation.context_updates for term_id in update.remove_term_ids}
    cleared = {update.role for update in interpretation.context_updates
        if update.term_id is None and not update.remove_term_ids}
    for selection in getattr(interpretation, 'selections', []) if not result.recommendation_group else []:
        if selection.term_id in final_ids and selection.term_id not in removed and selection.role not in cleared:
            state.setdefault('excluded_conditions', {}).pop(selection.term_id, None)
            constraints[selection.term_id] = dict(role=selection.role.value, term_id=selection.term_id,
                evidence=selection.evidence[0], source_job_id=str(selection.source_job_id or job['job_id']))
    if len(constraints) > 10:
        raise LLMInvalidStructuredOutput('Conversation cannot contain more than ten cards',
            stage='conversation_validation', feedback=[{'path': [], 'code': 'context_card_limit'}])
    state["constraints"] = constraints
    state["pending_question"] = result.clarifying_question
    return state
