"""Anonymous cookie owners and independently expiring conversations."""
from __future__ import annotations
import uuid
from typing import Any
from backend.shared.auth import hash_session_token

LIVE = "(s.retained OR s.last_activity_at + interval '3 months' > now())"
EXPIRY = "CASE WHEN s.retained THEN NULL ELSE s.last_activity_at + interval '3 months' END"


class SessionBusy(Exception):
    pass


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
               RETURNING owner_id, default_session_id, retained""",
            str(uuid.uuid4()), hash_session_token(token),
        )
        default = owner["default_session_id"]
        if not new and default is not None:
            existing = await connection.fetchval(
                f"SELECT session_id FROM sessions s WHERE session_id=$1 AND owner_id=$2 AND {LIVE}", default, owner["owner_id"],
            )
            if existing is not None:
                return str(existing)
        session_id = str(uuid.uuid4())
        await connection.execute(
            "INSERT INTO sessions(session_id, owner_id, retained) VALUES ($1::uuid,$2,$3)",
            session_id, owner["owner_id"], owner.get("retained", False),
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
                ON o.default_session_id=s.session_id AND o.owner_id=s.owner_id
                WHERE o.session_token_hash=$1 AND {LIVE}""", hash_session_token(token),
        )
        return str(value) if value else None

    async def has_owner(self, token: str) -> bool:
        return bool(token) and bool(await self._pool.fetchval(
            "SELECT 1 FROM anonymous_owners WHERE session_token_hash=$1", hash_session_token(token),
        ))

    async def list_sessions(self, token: str, limit=20, offset=0) -> list[dict]:
        rows = await self._pool.fetch(
            f"""SELECT s.*, {EXPIRY} AS expires_at
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
                        RETURNING s.*, {EXPIRY} AS expires_at"""
        else:
            query = f"""SELECT s.*, {EXPIRY} AS expires_at
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
            "DELETE FROM sessions WHERE NOT retained AND last_activity_at + interval '3 months' <= now()"
        )
        return int(result.rsplit(" ", 1)[-1])

    async def bind_local_profile(self, token: str) -> None:
        """Adopt this dedicated personal DB without deleting existing records."""
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                await connection.execute('SELECT pg_advisory_xact_lock(73492154)')
                owner_id = await connection.fetchval(
                    '''INSERT INTO anonymous_owners(owner_id, session_token_hash, retained)
                       VALUES ($1,$2,TRUE) ON CONFLICT(session_token_hash) DO UPDATE SET retained=TRUE
                       RETURNING owner_id''', uuid.uuid4(), hash_session_token(token))
                await connection.execute('''UPDATE sessions SET owner_id=$1,retained=TRUE
                    WHERE owner_id<>$1 OR NOT retained''', owner_id)
                await connection.execute('''UPDATE anonymous_owners SET default_session_id=NULL
                    WHERE owner_id<>$1 AND default_session_id IS NOT NULL''', owner_id)
                await connection.execute('''UPDATE anonymous_owners SET default_session_id=(
                    SELECT session_id FROM sessions WHERE owner_id=$1 ORDER BY last_activity_at DESC LIMIT 1)
                    WHERE owner_id=$1 AND default_session_id IS NULL''', owner_id)

    async def delete_session(self, token: str, session_id: str) -> None:
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                # Match ensure_session's owner -> session lock order.
                await connection.fetchval('''SELECT owner_id FROM anonymous_owners
                    WHERE session_token_hash=$1 FOR UPDATE''', hash_session_token(token))
                row = await connection.fetchval('''SELECT s.session_id FROM sessions s
                    JOIN anonymous_owners o USING(owner_id)
                    WHERE s.session_id=$1::uuid AND o.session_token_hash=$2 FOR UPDATE OF s''',
                    session_id, hash_session_token(token))
                if row is None:
                    return  # Idempotent; never disclose another owner's records.
                active = await connection.fetchval('''SELECT 1 FROM jobs WHERE session_id=$1
                    AND status NOT IN ('completed','failed') LIMIT 1''', row)
                if active:
                    raise SessionBusy
                await connection.execute('DELETE FROM sessions WHERE session_id=$1', row)


def session_view(row) -> dict:
    return {key: str(row[key]) if key == "session_id" else row[key]
            for key in ("session_id", "created_at", "last_activity_at", "expires_at")}
