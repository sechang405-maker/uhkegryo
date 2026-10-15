import json
from pathlib import Path
import pytest
from pydantic import ValidationError
from backend.schemas.models import InterpretationOutput, AgentResult
from backend.services.catalog_repository import load_catalog
from backend.services.resolver import resolve
from backend.services.response_assembler import assemble
from backend.services.llm import format_active_cards_json
from backend.services.structured_output import response_format

def output(ids):
    return InterpretationOutput(interpretation_state='select_terms', answer_text='각 조건을 별도 카드로 확인합니다.',
        selections=[dict(role=role,term_id=tid,confidence=.9,evidence=[evidence]) for role,tid,evidence in ids])

def test_same_category_and_mixed_categories_survive_resolution_and_restore():
    snapshot=load_catalog(Path('docs/domains/illustration-reference/term-cards'))
    ids=[('pose','pose_sitting','앉아서'),('pose','pose_action_two_hand_aiming','양손 조준'),
         ('view','view_front','정면'),('view','view_full_body','전신')]
    parsed=output(ids)
    result=assemble(resolve(parsed,snapshot,request_text='앉아서 양손 조준 정면 전신'),snapshot)
    restored=AgentResult.model_validate_json(result.model_dump_json())
    assert [t.term_id for t in restored.reference_plan.terms]==[x[1] for x in ids]
    assert 'rifle' not in restored.reference_plan.terms[0].search_url
    assert restored.reference_plan.terms[0].search_url != restored.reference_plan.terms[1].search_url

def test_duplicate_identity_and_global_limit_are_rejected():
    item=('pose','pose_sitting','앉기')
    with pytest.raises(ValidationError):output([item,item])
    with pytest.raises(ValidationError):output([('pose',f'pose_{i}','자세') for i in range(11)])

def test_model_schema_is_bounded_arrays_and_candidates_exclude_legacy_composites():
    snapshot=load_catalog(Path('docs/domains/illustration-reference/term-cards'))
    candidates=format_active_cards_json(snapshot)
    ids={c['term_id'] for c in json.loads(candidates)['active_cards']}
    assert 'pose_sitting' in ids and 'pose_action_two_hand_aiming' in ids
    assert 'pose_seated_two_hand_aiming' not in ids
    assert snapshot.get_active('pose_seated_two_hand_aiming') is not None  # old saved records
    schema=response_format(candidates)['json_schema']['schema']
    for field in ('selections','context_updates'):
        assert schema['properties'][field]['type']=='array'
        assert schema['properties'][field]['maxItems']==10

def test_new_selection_cannot_use_legacy_combined_card():
    snapshot=load_catalog(Path('docs/domains/illustration-reference/term-cards'))
    parsed=output([('pose','pose_seated_two_hand_aiming','앉아쏴')])
    assert resolve(parsed,snapshot,request_text='앉아쏴').status == 'all_invalid'
