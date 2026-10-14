"""Windows host launcher. No .env loading, automatic migrations, login, or data deletion."""
import os
from pathlib import Path
from urllib.parse import urlsplit

LOOPBACK = {'127.0.0.1', '::1', 'localhost'}


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
    args = parser.parse_args()
    from backend.shared.config import Settings, get_settings
    root = Path(__file__).resolve().parents[1]
    os.environ.update(LLM_BACKEND='codex-cli', WORKER_CONCURRENCY='1', ENVIRONMENT='development',
        LLM_MODEL='gpt-5.6-luna', INTERPRETER_PROMPT_VERSION='uhkegryo-interpreter-v4',
        INTERPRETER_PROMPT_PATH=str(root / 'prompts/uhkegryo-interpreter-v4.md'),
        LANGFUSE_PUBLIC_KEY='', LANGFUSE_SECRET_KEY='', MCP_ENABLED='false', MCP_BASE_URL='',
        SEARXNG_BASE_URL='', ALLOWED_ORIGINS='http://127.0.0.1:3100,http://localhost:3100')
    # Validate process env only; never silently import a copied team's .env/DB URL.
    settings = Settings(_env_file=None)
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
        asyncio.run(initialize())
        return
    import uvicorn
    uvicorn.run('backend.main:app', host='127.0.0.1', port=8000, workers=1,
                proxy_headers=False, loop='asyncio')


if __name__ == '__main__':
    main()
