import json
from copy import deepcopy
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from backend.services.catalog_repository import load_catalog, CatalogLoadError
from backend.services.llm import format_active_cards_json
from backend.services.resolver import resolve
from backend.services.response_assembler import assemble
from backend.schemas.models import InterpretationOutput, AgentResult

CATALOG = Path(__file__).parents[2] / 'docs/domains/illustration-reference/term-cards'


def test_seated_aiming_remains_combined_from_candidate_to_saved_result():
    snapshot = load_catalog(CATALOG)
    before = deepcopy(snapshot.get_active('pose_sitting'))
    card = snapshot.get_active('pose_seated_two_hand_aiming')
    assert card is not None
    assert card['component_term_ids'] == ['pose_sitting', 'pose_action_two_hand_aiming']
    candidate = next(c for c in json.loads(format_active_cards_json(snapshot))['active_cards']
                     if c['term_id'] == card['term_id'])
    assert '앉아쏴' in candidate['aliases_ko']
    assert len(candidate['components']) == 2
    output = InterpretationOutput(interpretation_state='select_terms', answer_text='앉아서 양손으로 조준하는 자세입니다.',
        selections=[dict(role='pose',term_id=card['term_id'],confidence=.95,evidence=['앉아쏴'])])
    result = assemble(resolve(output,snapshot,request_text='앉아쏴 자세 레퍼런스'),snapshot,answer_text=output.answer_text)
    restored = AgentResult.model_validate_json(result.model_dump_json())
    term = restored.reference_plan.terms[0]
    query = parse_qs(urlparse(term.search_url).query)['q'][0]
    assert 'seated' in query and 'rifle aiming' in query
    assert '앉' in term.label_ko and '조준' in term.label_ko
    assert snapshot.get_active('pose_sitting') == before


@pytest.mark.parametrize('bad', ['missing','blocked','wrong_component','incompatible','duplicate'])
def test_invalid_composition_fails_closed(write_catalog,card_factory,bad):
    base={**card_factory('pose_base'),'component':'primary'}
    action={**card_factory('pose_action',requires_any_of=['pose_base']),'component':'prop_action'}
    entry={'term_id':'pose_combined','base_term_id':'pose_base','action_term_id':'pose_action',
           'label_ko':'복합 자세','label_en':'compound pose','aliases_ko':[]}
    if bad=='missing':entry['action_term_id']='missing'
    if bad=='wrong_component':action['component']='primary'
    if bad=='incompatible':action['requires_any_of']=[]
    if bad=='duplicate':entry['term_id']='pose_base'
    extra={'pose_compositions':[entry]}
    if bad=='blocked':extra['pinterest_search_contract']={'direct_search_disabled_term_ids':['pose_action']}
    directory=write_catalog([('pose','pose.json')],{'pose':[base,action]},**extra)
    with pytest.raises(CatalogLoadError):load_catalog(directory)


def test_negative_alias_does_not_pass_grounding():
    snapshot=load_catalog(CATALOG)
    output=InterpretationOutput(interpretation_state='select_terms',answer_text='복합 자세',
        selections=[dict(role='pose',term_id='pose_seated_two_hand_aiming',confidence=.9,evidence=['앉아쏴'])])
    assert resolve(output,snapshot,request_text='앉아쏴 말고 그냥 앉은 자세').status == 'all_invalid'


def test_composite_condition_survives_followup_and_refresh():
    from backend.services import conversation_context, reference_update
    snapshot=load_catalog(CATALOG)
    output=InterpretationOutput(interpretation_state='select_terms',answer_text='앉아서 조준',
        selections=[dict(role='pose',term_id='pose_seated_two_hand_aiming',confidence=.9,evidence=['앉아쏴'])],
        context_updates=[dict(role='pose',term_id='pose_seated_two_hand_aiming',evidence='앉아쏴')])
    result=assemble(resolve(output,snapshot,request_text='앉아쏴'),snapshot)
    context={'state':{'constraints':{},'pending_question':None},'recent':[],'sources':[]}
    state=conversation_context.next_state(context,{'job_id':'00000000-0000-4000-8000-000000000001'},output,result)
    assert state['constraints']['pose']['term_id']=='pose_seated_two_hand_aiming'
    context.update(state=state,previous_result=result.model_dump(mode='json'),reference_action='refresh_all')
    previous=reference_update.previous_terms(context,snapshot)
    refresh=reference_update.refresh_resolution(previous,snapshot,context)
    assert refresh.terms[0].card['component_term_ids']==['pose_sitting','pose_action_two_hand_aiming']
    assert 'rifle aiming' in refresh.terms[0].card['query_fragments']
