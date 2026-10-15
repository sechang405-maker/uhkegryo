"""Reuse trusted prior cards and refresh each independent term."""
from dataclasses import replace

from backend.schemas.enums import AgentStatus, ReasonCode, Role
from backend.schemas.models import AgentResult, InterpretationSelection, ReferencePlan, ReferenceUpdate
from backend.services.resolver import ResolutionResult, ValidatedTerm, STATUS_CLARIFY, STATUS_PROCEED


def previous_terms(context, snapshot):
    payload = context.get('previous_result') or {}
    if not payload:
        return {}
    result = AgentResult.model_validate(payload)
    return {term.term_id: term for term in result.reference_plan.terms
            if (card := snapshot.get_active(term.term_id)) and card['role'] == term.role.value
            and not snapshot.is_direct_search_disabled(term.term_id)} if result.reference_plan else {}


def refresh_resolution(previous, snapshot, context):
    original = ((context.get('previous_result') or {}).get('reference_plan') or {}).get('terms', [])
    action = context.get('reference_action')
    if action == 'refresh_terms':
        requested = set(context.get('refresh_term_ids', []))
    elif action == 'refresh_roles':
        roles = set(context.get('refresh_roles', []))
        requested = {term['term_id'] for term in original if term['role'] in roles}
        if not roles <= {term['role'] for term in original}:
            requested = set()
    else:
        requested = {term['term_id'] for term in original}
    if not requested or not requested <= previous.keys():
        return ResolutionResult(status=STATUS_CLARIFY,
            reason_codes=[ReasonCode.INSUFFICIENT_VISUAL_EVIDENCE],
            clarifying_question='새로 찾을 카드나 조건을 알려주시겠어요?')
    return ResolutionResult(status=STATUS_PROCEED, terms=[ValidatedTerm(
        selection=InterpretationSelection(role=term.role, term_id=term.term_id,
            evidence=[term.label_ko], confidence=1), card=snapshot.get_active(term.term_id),
    ) for term_id, term in previous.items() if term_id in requested])


def select_searches(resolution, previous):
    if resolution.status != STATUS_PROCEED:
        return resolution
    return replace(resolution, terms=[term for term in resolution.terms
        if term.selection.term_id not in previous or term.selection.source_job_id is None])


def merge_preserved(result, previous, interpretation=None):
    if result.reference_plan is None:
        return result
    updates = interpretation.context_updates if interpretation else []
    removed = {term_id for item in updates for term_id in item.remove_term_ids}
    cleared = {item.role for item in updates if item.term_id is None and not item.remove_term_ids}
    terms = {term.term_id: term.model_copy(deep=True) for term in previous.values()
             if term.term_id not in removed and term.role not in cleared}
    terms.update({term.term_id: term for term in result.reference_plan.terms})
    ordered = [term for role in Role for term in terms.values() if term.role == role]
    codes = list(dict.fromkeys(code for term in ordered for code in term.reason_codes))
    resolved_roles = {term.role for term in ordered}
    return AgentResult(agent_status=AgentStatus.PARTIAL_RESULT if codes else AgentStatus.SUCCESS,
        reference_plan=ReferencePlan(terms=ordered,
            unresolved_roles=[role for role in result.reference_plan.unresolved_roles if role not in resolved_roles]),
        reason_codes=codes, answer_text=result.answer_text)


def annotate(result, context, replaced):
    if result.agent_status not in (AgentStatus.SUCCESS, AgentStatus.PARTIAL_RESULT, AgentStatus.NEEDS_CLARIFICATION):
        return result
    original = {term['term_id']: Role(term['role']) for term in
        ((context.get('previous_result') or {}).get('reference_plan') or {}).get('terms', [])}
    if result.agent_status is AgentStatus.NEEDS_CLARIFICATION:
        final, replaced = original, set()
    else:
        final = {term.term_id: term.role for term in result.reference_plan.terms}
        replaced = set(replaced) & final.keys()
    preserved, removed = final.keys() - replaced, original.keys() - final.keys()
    # Legacy category summaries are disjoint; precise decisions live in term IDs.
    replaced_roles = {final[key] for key in replaced}
    preserved_roles = set(final.values()) - replaced_roles
    removed_roles = set(original.values()) - set(final.values())
    result.reference_update = ReferenceUpdate(
        replaced_term_ids=[key for key in final if key in replaced],
        preserved_term_ids=[key for key in final if key in preserved],
        removed_term_ids=[key for key in original if key in removed],
        replaced_roles=[role for role in Role if role in replaced_roles],
        preserved_roles=[role for role in Role if role in preserved_roles],
        removed_roles=[role for role in Role if role in removed_roles])
    return result
