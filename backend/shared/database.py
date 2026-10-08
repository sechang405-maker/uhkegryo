from collections.abc import AsyncIterator

import asyncpg

from backend.shared.config import Settings


async def create_pool(settings: Settings):
    return await asyncpg.create_pool(settings.database_url)


async def close_pool(pool) -> None:
    await pool.close()


async def connection(pool) -> AsyncIterator:
    async with pool.acquire() as connection:
        yield connection
