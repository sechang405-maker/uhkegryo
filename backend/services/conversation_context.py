"""Bounded context, original-source validation, and recall orchestration."""
import re
from copy import deepcopy

from backend.schemas.enums import AgentStatus, ReasonCode, Role
from backend.services.clarification_policy import repeated_question, REPEATED_FALLBACK
from backend.schemas.models import AgentResult, InterpretationOutput, InterpretationSelection
from backend.schemas.memory import RecallQuery, RecallAnswer, MemorySource, NO_RECORDS, TOO_MANY
from backend.services.conversation_memory import evidence_text, normalize_constraints
from backend.services.llm import LLMInvalidStructuredOutput
from backend.services.resolver import resolve, ResolutionResult, STATUS_CLARIFY, STATUS_ALL_INVALID, STATUS_PROCEED

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
    return bool(re.search(r"체형|자세|포즈|시점|원근|배치|캐릭터|레퍼런스|\b(reference|pose|character|perspective)\b", text)
                and re.search(r"찾아|그려|보여|검색|\b(find|draw|show|search)\b", text))


async def validate(memory, job, interpretation, snapshot, *, context=None, updates_only=False):
    ids = [item.source_job_id for item in interpretation.selections if item.source_job_id]
    originals = await memory.records(job, ids) if ids else []
    by_id = {item["job_id"]: item for item in originals}
    verified_source_texts = {}
    for selection in interpretation.selections:
        if selection.source_job_id:
            original = by_id.get(str(selection.source_job_id))
            if original is None:
                raise LLMInvalidStructuredOutput("선택 출처가 검증된 선행 기록에 없습니다", stage="conversation_validation",
                                                 feedback=[{"path": [], "code": "selection_source_invalid"}])
            allowed = [original["request_text"]] + [t[k] for t in original["terms"] for k in ("label_ko", "label_en")]
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


def next_state(context, job, interpretation, result):
    state = deepcopy(context["state"])
    if result.agent_status is AgentStatus.REFERENCE_GUIDANCE:
        state['pending_question'] = None
        return state
    if result.agent_status not in (AgentStatus.SUCCESS, AgentStatus.PARTIAL_RESULT, AgentStatus.NEEDS_CLARIFICATION):
        return state
    if result.agent_status is AgentStatus.NEEDS_CLARIFICATION:
        state['pending_question'] = result.clarifying_question
        return state
    constraints = normalize_constraints(state.get("constraints", {}))
    for update in interpretation.context_updates if result.agent_status is not AgentStatus.NEEDS_CLARIFICATION else []:
        for term_id in update.remove_term_ids:
            constraints.pop(term_id, None)
        if update.term_id is None and not update.remove_term_ids:
            constraints = {key: value for key, value in constraints.items() if value["role"] != update.role.value}
        elif update.term_id is not None:
            constraints[update.term_id] = {"role": update.role.value, "term_id": update.term_id,
                "evidence": update.evidence, "source_job_id": str(job["job_id"])}
    if len(constraints) > 10:
        raise LLMInvalidStructuredOutput('Conversation cannot contain more than ten cards',
            stage='conversation_validation', feedback=[{'path': [], 'code': 'context_card_limit'}])
    state["constraints"] = constraints
    state["pending_question"] = result.clarifying_question
    return state
