import asyncio
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.shared.config import Settings


def test_google_invite_codex_settings_require_an_explicit_owner_account_id():
    configured_owner = '11111111-1111-1111-1111-111111111111'
    base = dict(
        _env_file=None, database_url='postgresql://u:p@127.0.0.1:55433/uh',
        llm_backend='codex-cli', worker_concurrency=1,
        interpreter_prompt_version='uhkegryo-interpreter-v4', auth_mode='google_invite',
        google_client_id='client', google_client_secret='secret',
        google_redirect_uri='http://localhost:8010/api/auth/google/callback',
        auth_frontend_origin='http://localhost:3110',
        invite_code_pepper='synthetic-pepper-long-enough',
    )
    with pytest.raises(ValueError):
        Settings(**base)

    configured = Settings(
        **base, codex_owner_account_id=configured_owner
    )
    assert str(configured.codex_owner_account_id) == configured_owner
    approved = base | {
        'codex_owner_account_id': configured_owner
    }
    for change in (
        {'google_redirect_uri': 'http://localhost:8000/api/auth/google/callback'},
        {'google_redirect_uri': 'https://example.test/api/auth/google/callback'},
        {'auth_frontend_origin': 'http://localhost:3100'},
        {'auth_frontend_origin': 'https://example.test'},
    ):
        with pytest.raises(ValueError):
            Settings(**(approved | change))


def test_local_backend_requires_loopback_db_and_single_worker():
    with pytest.raises(ValueError):
        Settings(_env_file=None, database_url='postgresql://user:pass@remote.invalid/db',
                 llm_backend='codex-cli', worker_concurrency=1)


def test_codex_child_environment_drops_keys_and_custom_auth_path():
    from backend.services.codex_runtime import child_environment
    env = child_environment({'PATH': 'bin', 'HOME': 'home', 'OPENAI_API_KEY': 'secret',
                             'CODEX_HOME': 'other-auth', 'DATABASE_URL': 'secret', 'LANGFUSE_SECRET_KEY': 'secret'})
    assert env == {'PATH': 'bin', 'HOME': 'home'}


def test_header_requires_exact_model_and_provider():
    from backend.services.codex_runtime import verified_header
    from backend.services.llm import LLMConfigurationError
    assert verified_header('model: gpt-5.6-luna\nprovider: openai\nuser\nmodel: other')['model'] == 'gpt-5.6-luna'
    for header in ('model: other\nprovider: openai', 'model: gpt-5.6-luna\nprovider: other', ''):
        with pytest.raises(LLMConfigurationError):
            verified_header(header)


def test_local_request_guard_rejects_remote_host_and_origin():
    from backend.local_codex import local_request_allowed
    assert local_request_allowed('127.0.0.1', '127.0.0.1:8000', 'http://127.0.0.1:3100')
    for peer, host, origin in [('8.8.8.8','localhost:8000',None), ('127.0.0.1','evil.test',None),
                               ('127.0.0.1','localhost','https://evil.test')]:
        assert not local_request_allowed(peer, host, origin)


def test_google_invite_codex_allows_only_the_configured_active_admin():
    from backend.local_codex import local_codex_account_allowed
    settings = SimpleNamespace(
        llm_backend='codex-cli', auth_mode='google_invite',
        codex_owner_account_id='11111111-1111-1111-1111-111111111111',
    )

    assert local_codex_account_allowed(settings, SimpleNamespace(
        account_id='11111111-1111-1111-1111-111111111111', role='admin', status='active',
    ))
    for account in (
        None,
        SimpleNamespace(role='admin', status='active'),
        SimpleNamespace(account_id='22222222-2222-2222-2222-222222222222', role='admin', status='active'),
        SimpleNamespace(account_id='11111111-1111-1111-1111-111111111111', role='user', status='active'),
        SimpleNamespace(account_id='11111111-1111-1111-1111-111111111111', role='admin', status='disabled'),
    ):
        assert not local_codex_account_allowed(settings, account)

    wrong_settings = SimpleNamespace(
        llm_backend='codex-cli', auth_mode='google_invite',
        codex_owner_account_id='22222222-2222-2222-2222-222222222222',
    )
    assert local_codex_account_allowed(wrong_settings, SimpleNamespace(
        account_id='22222222-2222-2222-2222-222222222222', role='admin', status='active',
    ))


def test_google_invite_codex_fails_closed_without_configured_owner():
    from backend.local_codex import local_codex_account_allowed
    settings = SimpleNamespace(llm_backend='codex-cli', auth_mode='google_invite')
    account = SimpleNamespace(
        account_id='11111111-1111-1111-1111-111111111111', role='admin', status='active',
    )

    assert not local_codex_account_allowed(settings, account)


def test_oauth_settings_retarget_only_the_existing_database_to_loopback(tmp_path, monkeypatch):
    from backend.local_codex import load_oauth_settings
    settings_file = tmp_path / 'oauth-local.env'
    settings_file.write_text(
        'DATABASE_URL=postgresql://uhkegryo:secret@app-db:5432/uhkegryo\n'
        'AUTH_MODE=google_invite\n'
        'GOOGLE_CLIENT_ID=synthetic-client\n'
        'GOOGLE_CLIENT_SECRET=synthetic-secret\n'
        'GOOGLE_REDIRECT_URI=http://localhost:8010/api/auth/google/callback\n'
        'AUTH_FRONTEND_ORIGIN=http://localhost:3110\n'
        'INVITE_CODE_PEPPER=synthetic-pepper-long-enough\n'
        'INVITE_REDEEM_ATTEMPT_LIMIT=5\n'
        'INVITE_REDEEM_WINDOW_SECONDS=900\n'
        'CODEX_OWNER_ACCOUNT_ID=11111111-1111-1111-1111-111111111111\n'
        'OPENROUTER_API_KEY=must-not-be-imported\n'
        'LOGIN_TEST_MODE=1\n',
        encoding='utf-8',
    )
    monkeypatch.delenv('OPENROUTER_API_KEY', raising=False)

    load_oauth_settings(settings_file, database_port=55433)

    assert os.environ['DATABASE_URL'] == 'postgresql://uhkegryo:secret@127.0.0.1:55433/uhkegryo'
    assert os.environ['AUTH_MODE'] == 'google_invite'
    assert os.environ['LOGIN_TEST_MODE'] == 'false'
    assert os.environ['CODEX_OWNER_ACCOUNT_ID'] == '11111111-1111-1111-1111-111111111111'
    assert 'OPENROUTER_API_KEY' not in os.environ


def test_codex_adapter_validates_without_constructing_openrouter(monkeypatch):
    from backend.services.codex_llm import CodexInterpretationAdapter
    import backend.services.llm as llm
    monkeypatch.setattr(llm.openai, 'AsyncOpenAI', lambda **kw: pytest.fail('paid client created'))
    settings = SimpleNamespace(interpreter_prompt_version='uhkegryo-interpreter-v4',
        codex_timeout_seconds=180, codex_bin_dir='', codex_executable='',
        llm_model='gpt-5.6-luna', langfuse_public_key='', langfuse_secret_key='')
    adapter = CodexInterpretationAdapter(settings=settings, system_message='rules', user_template='{{request_text}}')
    async def invalid(*args, **kwargs):
        return '{"unexpected":"not an interpretation"}'
    monkeypatch.setattr(adapter, '_generate', invalid)
    with pytest.raises(llm.LLMInvalidStructuredOutput):
        asyncio.run(adapter.interpret('합성 입력',job_id='j',session_id='s',attempt=1,max_attempts=1))


def test_local_settings_reject_concurrency_trace_search_and_remote_db_overrides():
    base = dict(_env_file=None, database_url='postgresql://u:p@127.0.0.1:55432/uh',
                llm_backend='codex-cli', worker_concurrency=1,
                interpreter_prompt_version='uhkegryo-interpreter-v4')
    assert Settings(**base).llm_model == 'gpt-5.6-luna'
    for change in ({'worker_concurrency': 2}, {'langfuse_secret_key': 'secret'},
                   {'mcp_base_url': 'http://localhost:8001'}, {'environment': 'production'},
                   {'database_url': base['database_url'] + '?host=remote.invalid'}):
        with pytest.raises(ValueError):
            Settings(**(base | change))


def test_runner_builds_hardened_command_and_refuses_model_fallback(monkeypatch):
    from backend.services import codex_runtime as runtime
    from backend.services.llm import LLMConfigurationError
    calls = []
    monkeypatch.setattr(runtime, 'resolve_codex', lambda settings: 'signed-codex.exe')
    model = ['gpt-5.6-luna']
    async def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        if command[1:3] == ['login', 'status']:
            return 0, 'Logged in using ChatGPT'
        Path(command[command.index('--output-last-message') + 1]).write_text('{"answer":"합성"}', encoding='utf-8')
        return 0, f'model: {model[0]}\nprovider: openai\nuser\n'
    monkeypatch.setattr(runtime, 'run_process', fake_run)
    settings = SimpleNamespace(codex_timeout_seconds=30)
    assert json.loads(asyncio.run(runtime.generate(settings, [{'role':'user','content':'synthetic'}],
        {'type':'object'}))) == {'answer':'합성'}
    cmd, kw = calls[-1]
    assert '--ignore-user-config' in cmd and '--ephemeral' in cmd
    assert cmd[cmd.index('--sandbox') + 1] == 'read-only'
    assert cmd[cmd.index('--model') + 1] == 'gpt-5.6-luna'
    assert 'features.shell_tool=false' in cmd and 'features.apps=false' in cmd
    assert 'web_search="disabled"' in cmd and 'model_provider="openai"' in cmd
    assert 'synthetic' not in ' '.join(cmd) and b'synthetic' in kw['stdin']
    assert not Path(kw['cwd']).exists()  # Ephemeral result directory was cleaned.
    model[0] = 'different-model'
    with pytest.raises(LLMConfigurationError):
        asyncio.run(runtime.generate(settings, [], {'type':'object'}))


def test_runner_never_calls_model_without_existing_chatgpt_login(monkeypatch):
    from backend.services import codex_runtime as runtime
    from backend.services.llm import LLMConfigurationError
    monkeypatch.setattr(runtime, 'resolve_codex', lambda settings: 'signed-codex.exe')
    calls = []
    async def not_logged_in(command, **kwargs):
        calls.append(command)
        return 1, 'not logged in'
    monkeypatch.setattr(runtime, 'run_process', not_logged_in)
    with pytest.raises(LLMConfigurationError):
        asyncio.run(runtime.generate(SimpleNamespace(codex_timeout_seconds=30), [], {}))
    assert len(calls) == 1 and calls[0][1:] == ['login', 'status']


def test_process_timeout_and_cancel_terminate_child(tmp_path):
    import os
    import sys
    from backend.services.codex_runtime import run_process, child_environment
    from backend.services.llm import LLMTimeout
    async def scenario():
        cmd = [sys.executable, '-c', 'import time; time.sleep(60)']
        with pytest.raises(LLMTimeout):
            await run_process(cmd, env=child_environment(os.environ), cwd=str(tmp_path), timeout=.1)
        pending = asyncio.create_task(run_process(cmd, env=child_environment(os.environ), cwd=str(tmp_path)))
        await asyncio.sleep(.1)
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(pending, 10)
    asyncio.run(scenario())


def test_signed_resolver_does_not_downgrade(monkeypatch, tmp_path):
    from backend.services import codex_runtime as runtime
    from backend.services.llm import LLMConfigurationError
    import os
    monkeypatch.setattr(runtime, 'sys', SimpleNamespace(platform='win32'))
    for name, stamp in [('1111111111111111', 100), ('2222222222222222', 200)]:
        path = tmp_path / name / 'codex.exe'
        path.parent.mkdir()
        path.touch()
        os.utime(path, (stamp, stamp))
    settings = SimpleNamespace(codex_executable='', codex_bin_dir=str(tmp_path))
    monkeypatch.setattr(runtime, 'verify_codex_signature', lambda path: path.parent.name.startswith('1'))
    with pytest.raises(LLMConfigurationError):
        runtime.resolve_codex(settings)


def test_adapter_serializes_requests_and_memory_schema(monkeypatch):
    from backend.services.codex_llm import CodexInterpretationAdapter
    from backend.schemas.memory import RecallQuery
    settings = SimpleNamespace(interpreter_prompt_version='uhkegryo-interpreter-v4',
        codex_timeout_seconds=10, llm_model='gpt-5.6-luna', langfuse_public_key='', langfuse_secret_key='')
    adapter = CodexInterpretationAdapter(settings=settings, system_message='rules', user_template='{{request_text}}')
    active = 0
    peak = 0
    async def fake_generate(*args):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(.01)
        active -= 1
        return '{}'
    monkeypatch.setattr(adapter, '_generate', fake_generate)
    async def run():
        output_format = adapter._memory_output_format(RecallQuery)
        schema = output_format['json_schema']['schema']
        assert schema['additionalProperties'] is False
        assert set(schema['required']) == set(schema['properties'])
        await asyncio.gather(*(adapter._request([],output_format=output_format) for _ in range(3)))
    asyncio.run(run())
    assert peak == 1


def test_codex_search_outcomes_explicitly_report_unavailable(monkeypatch):
    from backend.services.agent_worker import AgentJobWorker
    from backend.services.codex_llm import CodexInterpretationAdapter
    from backend.schemas.enums import Role, ReasonCode
    worker = object.__new__(AgentJobWorker)
    worker._adapter = object.__new__(CodexInterpretationAdapter)
    worker._mcp_gateway = None
    resolution = SimpleNamespace(terms=[SimpleNamespace(selection=SimpleNamespace(role=Role.BODY, term_id='body_slim'))])
    outcomes = asyncio.run(worker._search_outcomes(resolution, request_text='new images'))
    assert outcomes['body_slim'].code == ReasonCode.PIN_SEARCH_UNAVAILABLE


def test_launcher_invalid_database_does_not_print_connection_secret():
    import os
    import subprocess
    import sys
    from backend.services.codex_runtime import child_environment
    env = child_environment(os.environ)
    env['DATABASE_URL'] = 'postgresql://u:do-not-display-password@remote.invalid/uh'
    result = subprocess.run([sys.executable, '-m', 'backend.local_codex'],
        env=env, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=20)
    assert result.returncode != 0
    assert 'do-not-display-password' not in result.stdout + result.stderr
    assert 'Local Codex configuration invalid' in result.stderr


def test_local_settings_are_explicit_and_only_load_database(tmp_path, monkeypatch):
    import os
    from backend.local_codex import load_local_settings
    path = tmp_path / '.env.local-codex'
    path.write_text('LOCAL_POSTGRES_PASSWORD=synthetic\nDATABASE_URL=postgresql://u:synthetic@127.0.0.1:55432/uh\n')
    monkeypatch.delenv('LOCAL_POSTGRES_PASSWORD', raising=False)
    monkeypatch.setenv('DATABASE_URL', 'old')
    load_local_settings(path)
    assert os.environ['DATABASE_URL'] == 'postgresql://u:synthetic@127.0.0.1:55432/uh'
    assert 'LOCAL_POSTGRES_PASSWORD' not in os.environ
    path.write_text('DATABASE_URL=postgresql://u:secret@127.0.0.1/uh\nOPENAI_API_KEY=secret\n')
    with pytest.raises(SystemExit, match='Local settings invalid') as error:
        load_local_settings(path)
    assert 'secret' not in str(error.value)
