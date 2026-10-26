"""Atomic, cumulative AI request quota ledger for invited demo accounts."""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime
from typing import Any

from backend.schemas.demo_accounts import AccountUsage, QuotaOperation


class AccountUnavailable(Exception):
    pass


class QuotaExceeded(Exception):
    pass


class QuotaIdempotencyConflict(Exception):
    pass


class QuotaStateConflict(Exception):
    pass


class QuotaRepository:
    def __init__(self, pool: Any) -> None:
        self._pool = pool

    async def reserve(
        self, account_id: str, operation_kind: str, idempotency_key: str,
        request_fingerprint: str, resource_id: str | None = None,
    ) -> QuotaOperation:
        if operation_kind not in {"conversation", "personal_term_proposal"}:
            raise ValueError("unsupported operation kind")
        if not idempotency_key.strip() or not request_fingerprint.strip():
            raise ValueError("idempotency key and request fingerprint are required")
        account_uuid = uuid.UUID(account_id)
        key_hash = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                account = await connection.fetchrow(
                    "SELECT * FROM accounts WHERE account_id=$1 FOR UPDATE", account_uuid,
                )
                if account is None:
                    raise AccountUnavailable
                existing = await connection.fetchrow(
                    """SELECT * FROM ai_usage_operations
                       WHERE account_id=$1 AND operation_kind=$2 AND idempotency_key_hash=$3""",
                    account_uuid, operation_kind, key_hash,
                )
                if existing is not None:
                    if existing["request_fingerprint"] != request_fingerprint:
                        raise QuotaIdempotencyConflict
                    return _operation(existing)
                if account["status"] != "active":
                    raise AccountUnavailable
                used = await connection.fetchval(
                    """SELECT COALESCE(sum(units),0) FROM ai_usage_operations
                       WHERE account_id=$1 AND state IN ('reserved','charged')""", account_uuid,
                )
                if used >= account["ai_request_limit"]:
                    raise QuotaExceeded
                row = await connection.fetchrow(
                    """INSERT INTO ai_usage_operations(
                           operation_id,account_id,operation_kind,idempotency_key_hash,
                           request_fingerprint,resource_id)
                       VALUES($1,$2,$3,$4,$5,$6) RETURNING *""",
                    uuid.uuid4(), account_uuid, operation_kind, key_hash,
                    request_fingerprint, resource_id,
                )
                return _operation(row)

    async def charge(self, account_id: str, operation_id: str) -> QuotaOperation:
        return await self._finalize(account_id, operation_id, "charged", None)

    async def release(self, account_id: str, operation_id: str, *, reason: str) -> QuotaOperation:
        if not reason.strip():
            raise ValueError("release reason is required")
        return await self._finalize(account_id, operation_id, "released", reason)

    async def _finalize(
        self, account_id: str, operation_id: str, target: str, reason: str | None,
    ) -> QuotaOperation:
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                row = await connection.fetchrow(
                    """SELECT * FROM ai_usage_operations
                       WHERE operation_id=$1 AND account_id=$2 FOR UPDATE""",
                    uuid.UUID(operation_id), uuid.UUID(account_id),
                )
                if row is None:
                    raise AccountUnavailable
                if row["state"] == target:
                    return _operation(row)
                if row["state"] != "reserved":
                    raise QuotaStateConflict
                updated = await connection.fetchrow(
                    """UPDATE ai_usage_operations
                       SET state=$2,finalized_at=now(),updated_at=now(),release_reason=$3
                       WHERE operation_id=$1 RETURNING *""",
                    row["operation_id"], target, reason,
                )
                return _operation(updated)

    async def usage(self, account_id: str) -> AccountUsage:
        row = await self._pool.fetchrow(
            """SELECT a.ai_request_limit,
                      COALESCE(sum(o.units) FILTER (WHERE o.state='charged'),0) AS charged,
                      COALESCE(sum(o.units) FILTER (WHERE o.state='reserved'),0) AS reserved
               FROM accounts a LEFT JOIN ai_usage_operations o USING(account_id)
               WHERE a.account_id=$1 GROUP BY a.account_id""", uuid.UUID(account_id),
        )
        if row is None:
            raise AccountUnavailable
        limit = int(row["ai_request_limit"])
        charged, reserved = int(row["charged"]), int(row["reserved"])
        return AccountUsage(limit=limit, charged=charged, reserved=reserved,
                            remaining=max(0, limit - charged - reserved))

    async def list_recovery_candidates(
        self, *, before: datetime, limit: int = 100,
    ) -> list[QuotaOperation]:
        if limit < 1 or limit > 1000:
            raise ValueError("limit must be between 1 and 1000")
        rows = await self._pool.fetch(
            """SELECT * FROM ai_usage_operations
               WHERE state='reserved' AND reserved_at < $1
               ORDER BY reserved_at,operation_id LIMIT $2""", before, limit,
        )
        return [_operation(row) for row in rows]


def _operation(row: Any) -> QuotaOperation:
    data = dict(row)
    data["operation_id"] = str(data["operation_id"])
    data["account_id"] = str(data["account_id"])
    data.pop("idempotency_key_hash", None)
    return QuotaOperation(**data)
