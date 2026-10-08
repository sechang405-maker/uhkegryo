"""Anonymous cookie owners and independently expiring conversations."""
from __future__ import annotations
import uuid
from typing import Any
from backend.shared.auth import hash_session_token

LIVE = "s.last_activity_at + interval '3 months' > now()"


class SessionRepository:
    def __init__(self, pool: Any) -> None:
        self._pool = pool

    async def create_session(self, token: str) -> str:
        if not token:
            raise ValueError("token must not be empty")
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                return await self.ensure_session(connection, token, new=True)

    @staticmethod
    async def ensure_session(connection, token: str, *, new=False) -> str:
        if not token:
            raise ValueError("token must not be empty")
        owner = await connection.fetchrow(
            """INSERT INTO anonymous_owners(owner_id, session_token_hash)
               VALUES ($1::uuid, $2) ON CONFLICT (session_token_hash) DO UPDATE
               SET session_token_hash=EXCLUDED.session_token_hash
               RETURNING owner_id, default_session_id""",
            str(uuid.uuid4()), hash_session_token(token),
        )
        default = owner["default_session_id"]
        if not new and default is not None:
            existing = await connection.fetchval(
                f"SELECT session_id FROM sessions s WHERE session_id=$1 AND {LIVE}", default,
            )
            if existing is not None:
                return str(existing)
        session_id = str(uuid.uuid4())
        await connection.execute(
            "INSERT INTO sessions(session_id, owner_id) VALUES ($1::uuid,$2)",
            session_id, owner["owner_id"],
        )
        if not new or default is None:
            await connection.execute(
                "UPDATE anonymous_owners SET default_session_id=$2::uuid WHERE owner_id=$1",
                owner["owner_id"], session_id,
            )
        return session_id

    async def resolve_session(self, token: str) -> str | None:
        if not token:
            raise ValueError("token must not be empty")
        value = await self._pool.fetchval(
            f"""SELECT s.session_id FROM sessions s JOIN anonymous_owners o
                ON o.default_session_id=s.session_id
                WHERE o.session_token_hash=$1 AND {LIVE}""", hash_session_token(token),
        )
        return str(value) if value else None

    async def has_owner(self, token: str) -> bool:
        return bool(token) and bool(await self._pool.fetchval(
            "SELECT 1 FROM anonymous_owners WHERE session_token_hash=$1", hash_session_token(token),
        ))

    async def list_sessions(self, token: str, limit=20, offset=0) -> list[dict]:
        rows = await self._pool.fetch(
            f"""SELECT s.*, s.last_activity_at + interval '3 months' AS expires_at
                FROM sessions s JOIN anonymous_owners o USING(owner_id)
                WHERE o.session_token_hash=$1 AND {LIVE}
                ORDER BY s.last_activity_at DESC, s.session_id LIMIT $2 OFFSET $3""",
            hash_session_token(token), limit, offset,
        )
        return [session_view(row) for row in rows]

    async def get_session(self, token: str, session_id: str, *, touch=False) -> dict:
        from backend.services.job_repository import JobNotFound
        if touch:
            query = f"""UPDATE sessions s SET last_activity_at=now()
                        FROM anonymous_owners o WHERE o.owner_id=s.owner_id
                        AND o.session_token_hash=$1 AND s.session_id=$2::uuid AND {LIVE}
                        RETURNING s.*, s.last_activity_at + interval '3 months' AS expires_at"""
        else:
            query = f"""SELECT s.*, s.last_activity_at + interval '3 months' AS expires_at
                        FROM sessions s JOIN anonymous_owners o USING(owner_id)
                        WHERE o.session_token_hash=$1 AND s.session_id=$2::uuid AND {LIVE}"""
        row = await self._pool.fetchrow(query, hash_session_token(token), session_id)
        if row is None:
            raise JobNotFound
        return session_view(row)

    async def session_for_job(self, token: str, job_id: str) -> str:
        from backend.services.job_repository import JobNotFound
        value = await self._pool.fetchval(
            f"""SELECT s.session_id FROM jobs j JOIN sessions s USING(session_id)
                JOIN anonymous_owners o USING(owner_id)
                WHERE o.session_token_hash=$1 AND j.job_id=$2::uuid AND {LIVE}""",
            hash_session_token(token), job_id,
        )
        if value is None:
            raise JobNotFound
        return str(value)

    async def delete_expired_sessions(self) -> int:
        result = await self._pool.execute(
            "DELETE FROM sessions WHERE last_activity_at + interval '3 months' <= now()"
        )
        return int(result.rsplit(" ", 1)[-1])


def session_view(row) -> dict:
    return {key: str(row[key]) if key == "session_id" else row[key]
            for key in ("session_id", "created_at", "last_activity_at", "expires_at")}
