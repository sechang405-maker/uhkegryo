"""Read-only titles from saved reference cards; never expose request text."""
import json


def title_terms(value, catalog=None):
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return []
    if not isinstance(value, list):
        return []
    result = []
    seen = set()
    for term in value[:10]:
        if not isinstance(term, dict):
            term = {'term_id': term} if isinstance(term, str) else {}
        term_id = term.get('term_id')
        if not isinstance(term_id, str) or not term_id or term_id in seen:
            continue
        seen.add(term_id)
        label = term.get('label_ko')
        card = catalog.get_active(term_id) if catalog else None
        if not isinstance(label, str) or not label.strip():
            label = card.get('label_ko', '') if card else ''
        result.append({'term_id': term_id, 'label_ko': label.strip()[:300]})
    return result
