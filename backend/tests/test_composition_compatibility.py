import asyncio
from datetime import datetime, timezone
from uuid import uuid4

from backend.schemas.enums import Role
from backend.schemas.models import AgentResult, ReferencePlan
from backend.schemas.memory import RecallQuery
from backend.services.catalog_repository import load_catalog
from backend.services.conversation_memory import ConversationMemory, normalize_constraints, record


def term(role, term_id):
    return dict(role=role, term_id=term_id, label_ko=term_id, label_en=term_id,
                plain_meaning_ko=term_id, search_url='https://www.pinterest.com/search/pins/')


def test_canonical_enum_and_schema_keep_old_input_aliases():
    assert list(Role) == [Role.BODY, Role.POSE, Role.COMPOSITION, Role.PERSPECTIVE]
    assert Role('view') is Role('layout') is Role.COMPOSITION
    schema = ReferencePlan.model_json_schema()['$defs']['Role']
    assert schema['enum'] == ['body', 'pose', 'composition', 'perspective']


def test_legacy_catalog_merges_both_sources_without_losing_ids(write_catalog, card_factory):
    path = write_catalog([('view', ''), ('perspective', ''), ('layout', '')], {
        'view': [card_factory('view_front', role='view')],
        'perspective': [card_factory('perspective_depth', role='perspective')],
        'layout': [card_factory('layout_composition', role='layout')],
    })
    snapshot = load_catalog(path)
    assert snapshot.roles_order == (Role.COMPOSITION, Role.PERSPECTIVE)
    assert snapshot.role_terms[Role.COMPOSITION] == ['view_front', 'layout_composition']
    assert snapshot.active_count == 3
    assert all(snapshot.active_cards[key]['role'] == 'composition'
               for key in ('view_front', 'layout_composition'))


def test_old_board_order_is_stably_normalized_and_cards_survive():
    payload = dict(terms=[term('view', 'view_front'), term('perspective', 'perspective_depth'),
                          term('layout', 'layout_composition')], unresolved_roles=[])
    plan = ReferencePlan.model_validate(payload)
    assert [item.term_id for item in plan.terms] == ['view_front', 'layout_composition', 'perspective_depth']
    assert [item.role.value for item in plan.terms] == ['composition', 'composition', 'perspective']
    assert payload['terms'][0]['role'] == 'view'  # No mutation of stored input.


def test_legacy_replaced_view_and_preserved_layout_recover_card_intent():
    payload = dict(agent_status='success', reference_plan=dict(terms=[
        term('view', 'view_front'), term('perspective', 'perspective_depth'),
        term('layout', 'layout_composition')]), reference_update=dict(
            replaced_roles=['view'], preserved_roles=['perspective', 'layout'], removed_roles=[]))
    result = AgentResult.model_validate(payload)
    assert result.reference_update.replaced_term_ids == ['view_front']
    assert result.reference_update.preserved_term_ids == ['perspective_depth', 'layout_composition']
    assert result.reference_update.replaced_roles == [Role.COMPOSITION]
    assert result.reference_update.preserved_roles == [Role.PERSPECTIVE]
    assert len(result.reference_plan.terms) == 3
    assert AgentResult.model_validate(result.model_dump(mode='json')) == result


def test_old_role_keyed_constraints_keep_both_independent_cards():
    values = {'view': {'term_id': 'view_front', 'evidence': 'front'},
              'layout': {'term_id': 'layout_composition', 'evidence': 'center'}}
    normalized = normalize_constraints(values)
    assert set(normalized) == {'view_front', 'layout_composition'}
    assert all(item['role'] == 'composition' for item in normalized.values())
    assert 'role' not in values['view']


def test_recall_composition_query_includes_old_rows_without_writes():
    class Pool:
        async def fetch(self, sql, *args):
            assert "t->>'role' IN ('view','layout')" in sql
            assert args[3] == Role.COMPOSITION
            assert not any(word in sql.upper() for word in ('UPDATE ', 'DELETE ', 'INSERT '))
            return []
    job = dict(session_id=uuid4(), created_at=datetime.now(timezone.utc), job_id=uuid4())
    assert asyncio.run(ConversationMemory(Pool()).search(job, RecallQuery(mode='recall', role='composition'))) == []


def test_recall_records_expose_canonical_roles_and_original_ids():
    payload = dict(agent_status='success', reference_plan=dict(terms=[
        term('view', 'view_front'), term('layout', 'layout_composition')]))
    value = record(dict(job_id=uuid4(), request_text='original', status='completed', final_payload_json=payload))
    assert [(item['role'], item['term_id']) for item in value['terms']] == [
        ('composition', 'view_front'), ('composition', 'layout_composition')]


def test_refresh_legacy_board_roles_includes_both_original_categories(snapshot_factory, card_factory):
    from backend.services.reference_update import previous_terms, refresh_resolution
    context = dict(previous_result=dict(agent_status='success', reference_plan=dict(terms=[
        term('view', 'view_front'), term('perspective', 'perspective_depth'),
        term('layout', 'layout_composition')])), reference_action='refresh_roles',
        refresh_roles=[Role.COMPOSITION])
    snapshot = snapshot_factory([card_factory('view_front', role='view'),
        card_factory('layout_composition', role='layout'),
        card_factory('perspective_depth', role='perspective')])
    result = refresh_resolution(previous_terms(context, snapshot), snapshot, context)
    assert result.status == 'proceed'
    assert [item.selection.term_id for item in result.terms] == ['view_front', 'layout_composition']


def test_prepare_normalizes_legacy_board_for_all_memory_implementations():
    from backend.services.conversation_context import prepare
    class Memory:
        async def load(self, job):
            return dict(previous_result=dict(agent_status='success', reference_plan=dict(terms=[
                term('view', 'view_front'), term('layout', 'layout_composition')])))
    context = asyncio.run(prepare(Memory(), {}, None, None))
    assert [item['role'] for item in context['previous_result']['reference_plan']['terms']] == [
        'composition', 'composition']
