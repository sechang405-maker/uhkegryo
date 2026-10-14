"""Windows host launcher. No .env loading, automatic migrations, login, or data deletion."""
import os
import io
from pathlib import Path
from urllib.parse import urlsplit

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


def main():
    import argparse
    import asyncio
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--init-db', action='store_true', help='Explicitly apply migrations to the selected local DB')
    parser.add_argument('--local-settings', action='store_true', help='Explicitly load the personal .env.local-codex DB settings')
    parser.add_argument('--search-url', default='', help='Optional loopback SearXNG origin for catalog-only public image searches')
    args = parser.parse_args()
    from backend.shared.config import Settings, get_settings
    root = Path(__file__).resolve().parents[1]
    if args.local_settings:
        load_local_settings(root / '.env.local-codex')
    os.environ.update(LLM_BACKEND='codex-cli', WORKER_CONCURRENCY='1', ENVIRONMENT='development',
        LLM_MODEL='gpt-5.6-luna', INTERPRETER_PROMPT_VERSION='uhkegryo-interpreter-v4',
        INTERPRETER_PROMPT_PATH=str(root / 'prompts/uhkegryo-interpreter-v4.md'),
        LANGFUSE_PUBLIC_KEY='', LANGFUSE_SECRET_KEY='', MCP_ENABLED='false', MCP_BASE_URL='',
        SEARXNG_BASE_URL=args.search_url, ALLOWED_ORIGINS='http://127.0.0.1:3100,http://localhost:3100')
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
    uvicorn.run('backend.main:app', host='127.0.0.1', port=8000, workers=1,
                proxy_headers=False, loop='asyncio')


if __name__ == '__main__':
    main()
