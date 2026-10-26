"""Persistence boundary for invited accounts; OAuth verification is stage 2."""

from __future__ import annotations

import json
import uuid
from typing import Any

from backend.schemas.demo_accounts import DemoAccountRecord, InviteRecord


class AdminPermissionDenied(Exception):
    pass


class AccountNotFound(Exception):
    pass


class DemoAccountRepository:
    def __init__(self, pool: Any) -> None:
        self._pool = pool

    async def get_account(self, account_id: str) -> DemoAccountRecord:
        row = await self._pool.fetchrow("SELECT * FROM accounts WHERE account_id=$1", uuid.UUID(account_id))
        if row is None:
            raise AccountNotFound
        return _account(row)

    async def get_by_google_subject(self, google_subject: str) -> DemoAccountRecord | None:
        row = await self._pool.fetchrow(
            "SELECT * FROM accounts WHERE google_subject=$1", google_subject,
        )
        return _account(row) if row is not None else None

    async def record_google_login(
        self, google_subject: str, *, verified_email: str, display_name: str | None,
    ) -> DemoAccountRecord | None:
        row = await self._pool.fetchrow(
            """UPDATE accounts
               SET email_normalized=$2,display_name=$3,last_login_at=now(),updated_at=now()
               WHERE google_subject=$1 AND status='active' RETURNING *""",
            google_subject, verified_email.casefold(), display_name,
        )
        if row is None:
            row = await self._pool.fetchrow(
                "SELECT * FROM accounts WHERE google_subject=$1", google_subject,
            )
        return _account(row) if row is not None else None

    async def set_ai_request_limit(
        self, actor_account_id: str, target_account_id: str, new_limit: int, *, reason: str,
    ) -> DemoAccountRecord:
        if new_limit < 0:
            raise ValueError("new_limit must be non-negative")
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                actor = await _active_admin(connection, actor_account_id)
                target = await connection.fetchrow(
                    "SELECT * FROM accounts WHERE account_id=$1 FOR UPDATE", uuid.UUID(target_account_id),
                )
                if target is None:
                    raise AccountNotFound
                row = await connection.fetchrow(
                    """UPDATE accounts SET ai_request_limit=$2,updated_at=now()
                       WHERE account_id=$1 RETURNING *""", target["account_id"], new_limit,
                )
                await _audit(connection, actor["account_id"], target["account_id"],
                             "quota_limit_changed", {
                                 "previous_limit": target["ai_request_limit"],
                                 "new_limit": new_limit,
                                 "reason": reason,
                             })
                return _account(row)

    async def set_account_status(
        self, actor_account_id: str, target_account_id: str, status: str, *, reason: str,
    ) -> DemoAccountRecord:
        if status not in {"active", "disabled"}:
            raise ValueError("unsupported account status")
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                actor = await _active_admin(connection, actor_account_id)
                row = await connection.fetchrow(
                    """UPDATE accounts SET status=$2,updated_at=now()
                       WHERE account_id=$1 RETURNING *""", uuid.UUID(target_account_id), status,
                )
                if row is None:
                    raise AccountNotFound
                await _audit(connection, actor["account_id"], row["account_id"],
                             "account_disabled" if status == "disabled" else "account_enabled",
                             {"reason": reason})
                return _account(row)


async def _active_admin(connection: Any, account_id: str):
    row = await connection.fetchrow(
        "SELECT * FROM accounts WHERE account_id=$1 FOR UPDATE", uuid.UUID(account_id),
    )
    if row is None or row["role"] != "admin" or row["status"] != "active":
        raise AdminPermissionDenied
    return row


async def _audit(connection: Any, actor_id, target_id, action: str, details: dict) -> None:
    await connection.execute(
        """INSERT INTO admin_audit_events(
               event_id,actor_account_id,target_account_id,action,details_json)
           VALUES($1,$2,$3,$4,$5::jsonb)""",
        uuid.uuid4(), actor_id, target_id, action, json.dumps(details, ensure_ascii=False),
    )


def _account(row: Any) -> DemoAccountRecord:
    return DemoAccountRecord(**{**dict(row), "account_id": str(row["account_id"])})


def _invite(row: Any) -> InviteRecord:
    data = dict(row)
    data.pop("code_hash", None)
    data["invite_id"] = str(data["invite_id"])
    data["created_by_account_id"] = str(data["created_by_account_id"])
    if data["accepted_by_account_id"] is not None:
        data["accepted_by_account_id"] = str(data["accepted_by_account_id"])
    return InviteRecord(**data)
