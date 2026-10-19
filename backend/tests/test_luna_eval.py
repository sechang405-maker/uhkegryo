import asyncio
import json
from types import SimpleNamespace

import pytest
from scripts import run_luna_eval as runner


def test_fixed_selection_and_dry_run_do_not_construct_transport(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, 'make_adapter', lambda: pytest.fail('transport created'))
    with pytest.raises(ValueError): runner.load_cases(['LUNA-01'] * 16)
    with pytest.raises(ValueError): runner.load_cases(runner.CASE_IDS[:-1])
    metadata = asyncio.run(runner.run(tmp_path/'dry', runner.CASE_IDS, 'a'*40))
    assert metadata['mode'] == 'dry_run'
    assert metadata['usage'] == 'unknown'
    assert set(metadata['catalog_files_sha256']) == {'index.json', 'body.json', 'pose.json', 'composition.json', 'perspective.json'}
    assert not (tmp_path/'dry'/'results.jsonl').exists()


def test_inactive_expected_card_rejected_before_output_or_transport(tmp_path, monkeypatch):
    dataset=json.loads(runner.DATASET.read_text(encoding='utf-8'))
    dataset['cases'][-1]['expected']['required_terms'][0]='body_muscular'
    path=tmp_path/'bad.json';path.write_text(json.dumps(dataset),encoding='utf-8')
    monkeypatch.setattr(runner,'DATASET',path)
    monkeypatch.setattr(runner,'make_adapter',lambda:pytest.fail('transport constructed'))
    with pytest.raises(ValueError,match='inactive expected term'):
        asyncio.run(runner.run(tmp_path/'output',runner.CASE_IDS,'a'*40,execute=True))
    assert not (tmp_path/'output').exists()


def test_single_attempt_failures_are_sanitized_and_unknown_usage(tmp_path):
    from backend.services.llm import LLMTimeout
    class Fake:
        calls = 0
        async def interpret(self, text, **kwargs):
            self.calls += 1
            assert kwargs['attempt'] == kwargs['max_attempts'] == 1
            raise LLMTimeout('SECRET_MARKER must not be recorded')
    fake=Fake()
    asyncio.run(runner.run(tmp_path/'run',runner.CASE_IDS,'a'*40,execute=True,adapter_factory=lambda:fake))
    rows=[json.loads(x) for x in (tmp_path/'run'/'results.jsonl').read_text(encoding='utf-8').splitlines()]
    assert len(rows)==16 and fake.calls==12
    assert sum(r['status']=='timeout' for r in rows)==12
    assert all(r['usage']=='unknown' for r in rows)
    assert 'SECRET_MARKER' not in (tmp_path/'run'/'results.jsonl').read_text(encoding='utf-8')
    with pytest.raises(FileExistsError): asyncio.run(runner.run(tmp_path/'run',runner.CASE_IDS,'a'*40))


def test_configuration_failure_stops_remaining_generations(tmp_path):
    from backend.services.llm import LLMConfigurationError
    class Fake:
        calls=0
        async def interpret(self,*args,**kwargs):
            self.calls+=1
            raise LLMConfigurationError('private command path')
    fake=Fake()
    asyncio.run(runner.run(tmp_path/'run',runner.CASE_IDS,'b'*40,execute=True,adapter_factory=lambda:fake))
    assert fake.calls==1
    rows=[json.loads(x) for x in (tmp_path/'run'/'results.jsonl').read_text(encoding='utf-8').splitlines()]
    assert rows[-1]['status']=='not_run'


def test_expected_checks_do_not_credit_wrong_terms():
    case={'expected':{'state':'select_terms','required_terms':['body_slim'],'forbidden_terms':['body_muscular']}}
    wrong=SimpleNamespace(interpretation_state=SimpleNamespace(value='select_terms'),selections=[SimpleNamespace(term_id='body_muscular')])
    assert not all(runner.check_output(case,wrong).values())


def test_context_update_omission_and_erased_preserved_body_fail():
    from backend.schemas.models import InterpretationOutput
    cases=runner.load_cases(runner.CASE_IDS)
    output=InterpretationOutput(interpretation_state='select_terms',answer_text='합성 답변',
        selections=[{'role':'body','term_id':'body_muscular','evidence':['근육질'],'confidence':.9},
                    {'role':'pose','term_id':'pose_sitting','evidence':['앉은'],'confidence':.9}])
    assert not runner.check_output(cases[15],output)['context_updates']
    output=InterpretationOutput(interpretation_state='select_terms',answer_text='합성 답변',
        selections=[{'role':'pose','term_id':'pose_weight_shift','evidence':['한쪽 다리'],'confidence':.9}],
        context_updates=[{'role':'body','term_id':None,'evidence':'체형은 두고'},
                         {'role':'pose','term_id':'pose_weight_shift','evidence':'한쪽 다리'}])
    assert not runner.check_output(cases[14],output)['context_updates']


def test_real_adapter_with_mock_transport_validates_and_never_uses_db(tmp_path, monkeypatch):
    import asyncpg
    from backend.services import codex_runtime
    from backend.services.llm import LLMTimeout
    monkeypatch.setattr(asyncpg,'connect',lambda *a,**k:pytest.fail('DB used'))
    monkeypatch.setattr(asyncpg,'create_pool',lambda *a,**k:pytest.fail('DB pool used'))
    calls=[]
    async def generate(settings,messages,schema):
        calls.append(messages)
        if len(calls)>1:raise LLMTimeout('synthetic')
        return json.dumps({'interpretation_state':'select_terms','answer_text':'마른 체형으로 똑바로 선 정면 자세입니다.',
            'selections':[{'role':role,'term_id':term,'evidence':[evidence],'confidence':.95}
                for role,term,evidence in [('body','body_slim','마른 체형'),('pose','pose_standing','두 발로 똑바로 서서'),('view','view_front','정면'),('layout','layout_composition','자료')]],
            'unresolved_constraints':[],'clarifying_question':None,'clarification_type':None,'context_updates':[]})
    monkeypatch.setattr(codex_runtime,'generate',generate)
    asyncio.run(runner.run(tmp_path/'run',runner.CASE_IDS,'a'*40,execute=True,adapter_factory=runner.make_adapter))
    rows=[json.loads(x) for x in (tmp_path/'run'/'results.jsonl').read_text(encoding='utf-8').splitlines()]
    assert len(calls)==12 and rows[0]['passed_checks'] and rows[0]['verified_model']=='mock'
    assert rows[0]['qualitative_score'] is None
    assert rows[0]['extra_term_ids']==['layout_composition']
    assert rows[0]['review_flags']==['extra_terms_require_semantic_review']
