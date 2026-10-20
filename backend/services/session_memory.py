"""Small session-owned topic ledger; user literals are distinct from consent.

Only original user text supplies topics. Confirmed conditions continue to live in
constraints; exclusions invalidate older evidence without losing its provenance.
"""
from copy import deepcopy
import re

from backend.services.reference_intent import current_action_text
from backend.services.selection_grounding import has_affirmed_evidence

RECOMMENDATION_KEYS = ('recommendation_group', 'recommendation_adoption', 'recommendation_pending_group_id')
STATE_KEYS = ('memory_version', 'constraints', 'pending_question', 'current_topic', 'excluded_conditions',
              'topic_scope_id', 'recommendation_topic_scope', *RECOMMENDATION_KEYS)
REFERENCE_ALIASES = {
    'pose_standing': ('서 있는', '서있는'),
    'pose_sitting': ('앉아 있는', '앉아있는', '앉은'),
    'view_front': ('정면', '앞모습'),
    'view_three_quarter': ('3/4 방향', '3/4방향'),
}


def clear_scope(context, scope_id=None):
    context['state'].update(memory_version=1, constraints={}, pending_question=None, current_topic=None,
        excluded_conditions={}, topic_scope_id=scope_id, recommendation_topic_scope=None,
        **dict.fromkeys(RECOMMENDATION_KEYS))
    context.update(previous_result={}, sources=[], recent=[], _recommendation_topic_reset=True)


def reset_is_affirmed(text, evidence=None):
    """Check the user's reset clause, never a model-chosen slice of its negation."""
    text = re.sub(r'"[^"\n]*"|“[^”\n]*”|‘[^’\n]*’|(?<!\w)\x27[^\x27\n]*\x27', ' ', text)
    if evidence is not None and evidence not in text:
        return False
    cue = (r'새로\s*시작|(?:새로운|새|다른)\s*(?:주제|캐릭터|인물)|'
        r'주제.{0,8}바[꾸꿔]|추천.{0,8}잊|'
        r'\b(?:new (?:topic|character)|start (?:over|again)|forget (?:that|the recommendation))\b')
    for clause in re.split(r'[.!?\n,]|\b(?:but|instead)\b|하지만|대신', text, flags=re.I):
        clause = current_action_text(clause)
        matches = list(re.finditer(cue, clause, re.I))
        if not matches and evidence is not None and evidence in clause:
            matches = list(re.finditer(r'주제|캐릭터|인물|동물|배경|풍경|그림|\b(?:subject|topic|character|animal|landscape)\b', clause, re.I))
        for match in matches:
            before, after = clause[:match.start()], clause[match.end():]
            # Negation scopes over the subject/predicate in this clause. It need
            # not be immediately adjacent ("don't want a new character").
            if re.search(r'\b(?:do\s+not|don[\x27’]t|never|not|no|without)\b', before, re.I):
                continue
            predicate = re.sub(r'^\s*(?:으로|로|은|는|이|가|을|를|도)?\s*', '', after)
            if re.match(r'말고|아니|않|안\s*', predicate):
                continue
            if re.search(r'지\s*(?:마|말|않)', predicate):
                continue
            if (re.search(r'(?:라는|이란|란)\s*(?:말|표현|뜻|의미)', after)
                    or re.search(r'\b(?:what\s+does|meaning\s+of|definition\s+of)\b', before, re.I)):
                continue
            return True
    return False


def explicit_reset(text):
    return reset_is_affirmed(text)


def literal_terms(text, snapshot, aliases=None):
    """Prefer the longest specific catalog label over its nested generic label."""
    text = re.sub(r'"[^"\n]*"|“[^”\n]*”|‘[^’\n]*’|(?<!\w)\x27[^\x27\n]*\x27', ' ', text)
    matches = []
    for term_id, card in snapshot.active_cards.items():
        if card.get('component') == 'composite' or snapshot.is_direct_search_disabled(term_id):
            continue
        for label in (card['label_ko'], card['label_en'], *(aliases or {}).get(term_id, ())):
            if len(label.strip()) < 2:
                continue
            for match in re.finditer(re.escape(label), text, re.I):
                evidence = match.group()
                if has_affirmed_evidence(evidence, [text]):
                    matches.append((match.start(), match.end(), term_id, card['role'], evidence))
    selected = {}
    for start, end, term_id, role, evidence in sorted(matches, key=lambda m: -(m[1]-m[0])):
        if any(role == other[3] and start >= other[0] and end <= other[1]
               and end-start < other[1]-other[0] for other in matches):
            continue
        selected.setdefault(term_id, dict(role=role, term_id=term_id, evidence=evidence))
    return selected


def observe(state, job, snapshot):
    state = deepcopy(state)
    terms = literal_terms(job['request_text'], snapshot, REFERENCE_ALIASES)
    if terms:
        state['memory_version'] = 1
        scope = state.setdefault('topic_scope_id', str(job['job_id']))
        state['current_topic'] = dict(scope_id=scope, source_job_id=str(job['job_id']),
            request_text=job['request_text'], terms=[dict(value, source_job_id=str(job['job_id'])) for value in terms.values()])
    return state


def source_ids(state):
    topic = state.get('current_topic') or {}
    return [value['source_job_id'] for value in topic.get('terms', []) if value.get('source_job_id')]


def prune_nested(selections, snapshot):
    """The model's select_terms path obeys the same specificity rule."""
    def labels(item):
        card = snapshot.get_active(item.term_id) or {}
        return [card.get('label_ko', ''), card.get('label_en', '')]
    return [item for item in selections if not any(item.role == other.role and item.term_id != other.term_id
        and any(a and b and a.casefold() != b.casefold() and a.casefold() in b.casefold()
                for a in labels(item) for b in labels(other)) for other in selections)]
