"""Materialize explicitly declared pose/action pairs; never compose user text."""
from copy import deepcopy
import re


def pose_compositions(entries, cards, feedback, blocked):
    if not isinstance(entries, list) or len(entries) > 20:
        raise ValueError('pose_compositions must be a bounded list')
    generated, generated_feedback = {}, {}
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {
            'term_id', 'base_term_id', 'action_term_id', 'label_ko', 'label_en', 'aliases_ko'
        }:
            raise ValueError('invalid pose composition declaration')
        identity = entry['term_id']
        if (not isinstance(identity, str) or not re.fullmatch(r'pose_[a-z0-9_]{1,110}', identity)
                or identity in cards or identity in generated or identity in blocked):
            raise ValueError('duplicate or invalid composition identity')
        if any(not isinstance(entry[key], str) or not entry[key].strip() or len(entry[key]) > 120
               for key in ('base_term_id', 'action_term_id', 'label_ko', 'label_en')):
            raise ValueError('invalid composition labels or source identities')
        aliases = entry['aliases_ko']
        if (not isinstance(aliases, list) or len(aliases) > 10
                or any(not isinstance(v, str) or not v.strip() or len(v) > 100 for v in aliases)):
            raise ValueError('invalid composition aliases')
        ids = [entry['base_term_id'], entry['action_term_id']]
        if any(key not in cards or key in blocked for key in ids):
            raise ValueError('composition source is missing, inactive or blocked')
        base, action = (cards[key] for key in ids)
        if (base['role'] != 'pose' or action['role'] != 'pose'
                or base.get('component') != 'primary' or action.get('component') != 'prop_action'
                or ids[0] not in action.get('requires_any_of', [])
                or not set(action.get('requires_all_of', [])) <= {ids[0]}):
            raise ValueError('incompatible pose/action components')
        parts = [base, action]
        # Keep complete curated fragments. Deduplicate exact fragments only; no freeform query text.
        fragments = list(dict.fromkeys(fragment for card in parts for fragment in card['query_fragments']))
        checkpoints = list(dict.fromkeys(point for card in parts for point in
            feedback.get(card['term_id'], {}).get('reference_checkpoints_ko', card['look_for'])))
        meaning = ' '.join(feedback.get(card['term_id'], {}).get('plain_meaning_ko', card['source_answer_draft'])
                           for card in parts)
        components = [{'term_id': card['term_id'], 'label_ko': card['label_ko'],
                       'confidence_gate': deepcopy(card['confidence_gate'])} for card in parts]
        generated[identity] = {
            'term_id': identity, 'role': 'pose', 'component': 'composite',
            'component_term_ids': ids, 'components': components, 'aliases_ko': list(aliases),
            'label_ko': entry['label_ko'], 'label_en': entry['label_en'],
            'query_fragments': fragments, 'look_for': checkpoints, 'source_answer_draft': meaning,
            'confidence_gate': {'require_all': [part['label_ko'] + '의 명시적 단서' for part in parts],
                                'do_not_infer_from': ['한 구성요소의 단서만 있음', '구성요소 중 하나를 부정함']},
            'requires_all_of': ids, 'requires_any_of': [], 'runtime_eligible': True,
            'mvp_status': 'active_in_current_contract', 'source_type': 'catalog_composition',
        }
        generated_feedback[identity] = {
            'plain_meaning_ko': meaning,
            'selection_reason_template_ko': entry['label_ko'] + '의 지지 자세와 행동을 함께 참고합니다.',
            'reference_checkpoints_ko': checkpoints,
        }
    return generated, generated_feedback
