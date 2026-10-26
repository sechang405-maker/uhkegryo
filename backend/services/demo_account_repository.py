"""Persistence boundary for invited accounts; OAuth verification is stage 2."""

from __future__ import annotations

import json
import uuid
from typing import Any

from backend.schemas.demo_accounts import DemoAccountRecord, InviteRecord


class AdminPermissionDenied(Exception):
    pass


class InviteUnavailable(Exception):
    pass


class AccountConflict(Exception):
    pass


class AccountNotFound(Exception):
    pass


class DemoAccountRepository:
    def __init__(self, pool: Any) -> None:
        self._pool = pool

    async def create_invite(self, actor_account_id: str, email: str) -> InviteRecord:
        normalized = _normalize_email(email)
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                actor = await _active_admin(connection, actor_account_id)
                row = await connection.fetchrow(
                    """INSERT INTO invites(invite_id,email_normalized,created_by_account_id)
                       VALUES($1,$2,$3) ON CONFLICT(email_normalized) DO NOTHING
                       RETURNING *""",
                    uuid.uuid4(), normalized, actor["account_id"],
                )
                if row is None:
                    existing = await connection.fetchrow(
                        "SELECT * FROM invites WHERE email_normalized=$1 FOR UPDATE", normalized,
                    )
                    if existing is not None and existing["status"] == "pending":
                        return _invite(existing)
                    raise InviteUnavailable
                await _audit(connection, actor["account_id"], None, "invite_created", {
                    "email_normalized": normalized,
                })
                return _invite(row)

    async def accept_invite(
        self, *, google_subject: str, verified_email: str, display_name: str | None = None,
    ) -> DemoAccountRecord:
        subject = google_subject.strip()
        if not subject:
            raise ValueError("google_subject is required")
        normalized = _normalize_email(verified_email)
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                by_subject = await connection.fetchrow(
                    "SELECT * FROM accounts WHERE google_subject=$1 FOR UPDATE", subject,
                )
                by_email = await connection.fetchrow(
                    "SELECT * FROM accounts WHERE email_normalized=$1 FOR UPDATE", normalized,
                )
                if by_subject is not None or by_email is not None:
                    if (by_subject is None or by_email is None
                            or by_subject["account_id"] != by_email["account_id"]):
                        raise AccountConflict
                    return _account(by_subject)
                invitation = await connection.fetchrow(
                    """SELECT * FROM invites WHERE email_normalized=$1 AND status='pending'
                       FOR UPDATE""", normalized,
                )
                if invitation is None:
                    raise InviteUnavailable
                account_id = uuid.uuid4()
                row = await connection.fetchrow(
                    """INSERT INTO accounts(
                           account_id,google_subject,email_normalized,display_name,last_login_at)
                       VALUES($1,$2,$3,$4,now()) RETURNING *""",
                    account_id, subject, normalized, display_name,
                )
                await connection.execute(
                    """INSERT INTO anonymous_owners(owner_id,account_id)
                       VALUES($1,$2)""", uuid.uuid4(), account_id,
                )
                await connection.execute(
                    """UPDATE invites SET status='accepted',accepted_by_account_id=$2,accepted_at=now()
                       WHERE invite_id=$1""", invitation["invite_id"], account_id,
                )
                return _account(row)

    async def get_account(self, account_id: str) -> DemoAccountRecord:
        row = await self._pool.fetchrow("SELECT * FROM accounts WHERE account_id=$1", uuid.UUID(account_id))
        if row is None:
            raise AccountNotFound
        return _account(row)

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


def _normalize_email(email: str) -> str:
    value = email.strip().casefold()
    if not value or "@" not in value or value.startswith("@") or value.endswith("@"):
        raise ValueError("a valid email is required")
    return value


def _account(row: Any) -> DemoAccountRecord:
    return DemoAccountRecord(**{**dict(row), "account_id": str(row["account_id"])})


def _invite(row: Any) -> InviteRecord:
    data = dict(row)
    data["invite_id"] = str(data["invite_id"])
    data["created_by_account_id"] = str(data["created_by_account_id"])
    if data["accepted_by_account_id"] is not None:
        data["accepted_by_account_id"] = str(data["accepted_by_account_id"])
    return InviteRecord(**data)
