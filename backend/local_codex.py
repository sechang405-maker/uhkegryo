"""Windows host launcher. No .env loading, automatic migrations, login, or data deletion."""
import os
import io
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

LOOPBACK = {'127.0.0.1', '::1', 'localhost'}


def load_local_settings(path):
    """Read only the explicitly selected, Git-ignored personal DB settings."""
    from dotenv import dotenv_values
    try:
        values = dotenv_values(stream=io.StringIO(Path(path).read_text(encoding='utf-8')), interpolate=False)
        if set(values) != {'DATABASE_URL', 'LOCAL_POSTGRES_PASSWORD'} or not all(values.values()):
            raise ValueError('invalid keys')
        os.environ['DATABASE_URL'] = values['DATABASE_URL']
    except (OSError, ValueError):
        raise SystemExit('Local settings invalid; check .env.local-codex without sharing its contents') from None


def load_oauth_settings(path, *, database_port):
    """Load only the existing local OAuth app settings and retarget its DB to loopback."""
    from dotenv import dotenv_values
    allowed = (
        'AUTH_MODE', 'GOOGLE_CLIENT_ID', 'GOOGLE_CLIENT_SECRET', 'GOOGLE_REDIRECT_URI',
        'AUTH_FRONTEND_ORIGIN', 'INVITE_CODE_PEPPER', 'INVITE_REDEEM_ATTEMPT_LIMIT',
        'INVITE_REDEEM_WINDOW_SECONDS', 'CODEX_OWNER_ACCOUNT_ID',
    )
    try:
        values = dotenv_values(
            stream=io.StringIO(Path(path).read_text(encoding='utf-8')), interpolate=False,
        )
        database = urlsplit(values.get('DATABASE_URL') or '')
        if (
            values.get('AUTH_MODE') != 'google_invite'
            or not all(values.get(key) for key in allowed)
            or database.scheme not in ('postgresql', 'postgres')
            or database.hostname != 'app-db'
            or '@' not in database.netloc
            or database.query
            or database.fragment
            or not 1 <= int(database_port) <= 65535
        ):
            raise ValueError()
        credentials = database.netloc.rsplit('@', 1)[0]
        local_database = urlunsplit((
            database.scheme, f'{credentials}@127.0.0.1:{int(database_port)}',
            database.path, '', '',
        ))
        for key in allowed:
            os.environ[key] = values[key]
        os.environ['DATABASE_URL'] = local_database
        os.environ['LOGIN_TEST_MODE'] = 'false'
    except (OSError, TypeError, ValueError):
        raise SystemExit('OAuth settings invalid; check the selected local settings without sharing contents') from None


def local_request_allowed(peer, host, origin):
    try:
        host_url = urlsplit('http://' + host)
        if peer not in LOOPBACK or host_url.hostname not in LOOPBACK or host_url.username or host_url.password:
            return False
        if origin:
            parsed = urlsplit(origin)
            if parsed.scheme not in ('http', 'https') or parsed.hostname not in LOOPBACK or parsed.username:
                return False
        return True
    except ValueError:
        return False


def local_codex_account_allowed(settings, account):
    """Keep a personal host Codex login confined to its configured account."""
    if (
        getattr(settings, 'llm_backend', 'openrouter') != 'codex-cli'
        or getattr(settings, 'auth_mode', 'local') != 'google_invite'
    ):
        return True
    owner_account_id = getattr(settings, 'codex_owner_account_id', None)
    return bool(
        owner_account_id is not None
        and account is not None
        and str(getattr(account, 'account_id', '')) == str(owner_account_id)
        and getattr(account, 'role', None) == 'admin'
        and getattr(account, 'status', None) == 'active'
    )


def main():
    import argparse
    import asyncio
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--init-db', action='store_true', help='Explicitly apply migrations to the selected local DB')
    parser.add_argument('--local-settings', action='store_true', help='Explicitly load the personal .env.local-codex DB settings')
    parser.add_argument('--oauth-settings', default='', help='Explicit local Google OAuth settings file')
    parser.add_argument('--database-port', type=int, default=55433, help='Loopback port mapped to the existing app DB')
    parser.add_argument('--port', type=int, default=8000, help='Loopback API port')
    parser.add_argument('--frontend-port', type=int, default=3100, help='Loopback frontend port')
    parser.add_argument('--search-url', default='', help='Optional loopback SearXNG origin for catalog-only public image searches')
    args = parser.parse_args()
    from backend.shared.config import Settings, get_settings
    root = Path(__file__).resolve().parents[1]
    if args.local_settings and args.oauth_settings:
        raise SystemExit('Choose one local settings source')
    if args.oauth_settings:
        load_oauth_settings(args.oauth_settings, database_port=args.database_port)
    elif args.local_settings:
        load_local_settings(root / '.env.local-codex')
    os.environ.update(LLM_BACKEND='codex-cli', WORKER_CONCURRENCY='1', ENVIRONMENT='development',
        LLM_MODEL='gpt-5.6-luna', INTERPRETER_PROMPT_VERSION='uhkegryo-interpreter-v4',
        INTERPRETER_PROMPT_PATH=str(root / 'prompts/uhkegryo-interpreter-v4.md'),
        LANGFUSE_PUBLIC_KEY='', LANGFUSE_SECRET_KEY='', MCP_ENABLED='false', MCP_BASE_URL='',
        OPENROUTER_API_KEY='', OPENAI_API_KEY='', ANTHROPIC_API_KEY='',
        SEARXNG_BASE_URL=args.search_url,
        ALLOWED_ORIGINS=(f'http://127.0.0.1:{args.frontend_port},http://localhost:{args.frontend_port}'))
    # Validate process env only; never silently import a copied team's .env/DB URL.
    try:
        settings = Settings(_env_file=None)
    except ValueError:
        raise SystemExit('Local Codex configuration invalid; check the local DATABASE_URL and documented settings') from None
    if args.local_settings:
        from backend.local_profile import load_or_create_profile
        settings.local_profile_token = load_or_create_profile(root / '.env.local-profile')
    get_settings.cache_clear()
    import backend.shared.config as config
    config.get_settings = lambda: settings
    if args.init_db:
        async def initialize():
            import asyncpg
            from backend.db.migrate import migrate
            connection = await asyncpg.connect(settings.database_url)
            try:
                await migrate(connection)
            finally:
                await connection.close()
        try:
            asyncio.run(initialize())
        except Exception:
            raise SystemExit('Local DB initialization failed; check the selected local database and schema') from None
        return
    import uvicorn
    uvicorn.run('backend.main:app', host='127.0.0.1', port=args.port, workers=1,
                proxy_headers=False, loop='asyncio')


if __name__ == '__main__':
    main()
