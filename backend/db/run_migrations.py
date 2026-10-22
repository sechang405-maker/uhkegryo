"""Run every pending PostgreSQL migration once and exit."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

import asyncpg

from backend.db.migrate import migrate
from backend.shared.config import get_settings


async def run_migrations(
    database_url: str,
    *,
    connect: Callable[[str], Awaitable[Any]] = asyncpg.connect,
    migrate_schema: Callable[[Any], Awaitable[None]] = migrate,
) -> None:
    connection = await connect(database_url)
    try:
        await migrate_schema(connection)
    finally:
        await connection.close()


def main() -> None:
    asyncio.run(run_migrations(get_settings().database_url))


if __name__ == "__main__":
    main()
