"""Narrow lexical contradictions only; natural-language meaning still needs interpretation."""
import re

from backend.services.input_safety import normalize_input_text


_GENERIC_MOTION_CARD_TERMS = {
    "pose_gesture": ("동세", "액션 라인", "gesture drawing", "action line"),
    "pose_action": ("액션 포즈", "action pose"),
}
_NAMED_ACTIVITY_REQUEST = re.compile(
    r"[가-힣a-z0-9_-]{2,24}(?:을|를)?\s*하(?:는|고\s*있는)\s*(?:동작|자세|포즈)",
    re.IGNORECASE,
)


def overgeneralizes_named_activity(selection, sources):
    """Reject a generic motion-technique card for a distinct requested activity.

    A request such as ``발레를 하는 동작`` is not evidence that the user asked
    for the catalog's generic ``동세/액션 라인`` technique.  Explicit requests
    for that technique remain valid, as do selections of specific supported
    activity cards such as running.
    """
    explicit_terms = _GENERIC_MOTION_CARD_TERMS.get(selection.term_id)
    if not explicit_terms:
        return False
    normalized_sources = [normalize_input_text(source).casefold() for source in sources]
    if any(term.casefold() in source for source in normalized_sources for term in explicit_terms):
        return False
    return any(_NAMED_ACTIVITY_REQUEST.search(source) for source in normalized_sources)


def has_affirmed_evidence(evidence, sources):
    """Require a source occurrence not immediately excluded or marked uncertain.

    This deliberately handles a small set of explicit forms, not arbitrary negation.
    Source text must already have passed current-request/verified-history ownership checks.
    """
    text = normalize_input_text(evidence)
    if not text:
        return False
    pattern = re.escape(text)
    if text[0].isascii() and text[0].isalnum():
        pattern = r"(?<![a-z0-9_])" + pattern
    if text[-1].isascii() and text[-1].isalnum():
        pattern += r"(?![a-z0-9_])"
    for source in sources:
        for match in re.finditer(pattern, source, re.IGNORECASE):
            before, after = source[:match.start()], source[match.end():]
            if re.search(r"\b(?:not|no|without|maybe|perhaps)\s+$", before, re.IGNORECASE):
                continue
            suffix = re.sub(r"^(?:은|는|이|가|을|를)?\s*", "", after)
            # These explicit additive/keep forms must not be truncated into exclusions.
            if re.match(r"말고도|제외하지\s*(?:마|말|않)|빼고\s*싶지\s*않", suffix):
                return True
            if re.match(r"말고|아닌|아니라|제외|빼고|인지\s*모르|일지\s*모르", suffix):
                continue
            return True
    return False


def only_names_other_cards(selection, snapshot):
    """Reject evidence consisting solely of another same-role card's exact labels.

    Additional descriptive evidence and catalog parent/child relations stay with the
    interpreter; an exact label is not treated as a complete semantic classifier.
    """
    matched_ids = set()
    for evidence in selection.evidence:
        text = normalize_input_text(evidence).casefold()
        matches = {term_id for term_id, card in snapshot.active_cards.items()
            if str(card["role"]) == str(selection.role)
            and text in {normalize_input_text(card[key]).casefold() for key in ("label_ko", "label_en")}}
        if not matches:
            return False
        matched_ids.update(matches)
    if selection.term_id in matched_ids:
        return False
    selected = snapshot.get_active(selection.term_id)
    related = set(selected.get("requires_all_of", []) + selected.get("requires_any_of", []))
    for term_id in matched_ids:
        card = snapshot.get_active(term_id)
        if selection.term_id in card.get("requires_all_of", []) + card.get("requires_any_of", []):
            related.add(term_id)
    return bool(matched_ids - related) and not bool(matched_ids & related)
