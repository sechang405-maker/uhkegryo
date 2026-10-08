"""Run the daily expired-session cleanup as a one-shot scheduled task."""
from __future__ import annotations

import asyncio

from backend.services.session_repository import SessionRepository
from backend.shared.config import get_settings
from backend.shared.database import close_pool, create_pool


async def cleanup_expired_sessions() -> int:
    pool = await create_pool(get_settings())
    try:
        return await SessionRepository(pool).delete_expired_sessions()
    finally:
        await close_pool(pool)


if __name__ == "__main__":
    print(asyncio.run(cleanup_expired_sessions()))
