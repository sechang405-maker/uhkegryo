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
                return await self.reserve_on(
                    connection, account_id, operation_kind, idempotency_key,
                    request_fingerprint, resource_id,
                )

    async def reserve_on(
        self, connection: Any, account_id: str, operation_kind: str,
        idempotency_key: str, request_fingerprint: str,
        resource_id: str | None = None,
    ) -> QuotaOperation:
        """Reserve one unit inside an existing transaction.

        The account row is the serialization point shared by conversations and
        personal-term generation. A released operation may be reserved again for
        an explicit retry, while a charged operation stays idempotently final.
        """
        if operation_kind not in {"conversation", "personal_term_proposal"}:
            raise ValueError("unsupported operation kind")
        if not idempotency_key.strip() or not request_fingerprint.strip():
            raise ValueError("idempotency key and request fingerprint are required")
        account_uuid = uuid.UUID(account_id)
        key_hash = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()
        account = await connection.fetchrow(
            "SELECT * FROM accounts WHERE account_id=$1 FOR UPDATE", account_uuid,
        )
        if account is None:
            raise AccountUnavailable
        existing = await connection.fetchrow(
            """SELECT * FROM ai_usage_operations
               WHERE account_id=$1 AND operation_kind=$2 AND idempotency_key_hash=$3
               FOR UPDATE""",
            account_uuid, operation_kind, key_hash,
        )
        if existing is not None:
            if existing["request_fingerprint"] != request_fingerprint:
                raise QuotaIdempotencyConflict
            if existing["state"] != "released":
                return _operation(existing)
        if account["status"] != "active":
            raise AccountUnavailable
        used = await connection.fetchval(
            """SELECT COALESCE(sum(units),0) FROM ai_usage_operations
               WHERE account_id=$1 AND state IN ('reserved','charged')""", account_uuid,
        )
        if not account["ai_quota_unlimited"] and used >= account["ai_request_limit"]:
            raise QuotaExceeded
        if existing is not None:
            row = await connection.fetchrow(
                """UPDATE ai_usage_operations
                   SET state='reserved',resource_id=COALESCE($2,resource_id),
                       reserved_at=now(),finalized_at=NULL,updated_at=now(),release_reason=NULL
                   WHERE operation_id=$1 RETURNING *""",
                existing["operation_id"], resource_id,
            )
        else:
            row = await connection.fetchrow(
                """INSERT INTO ai_usage_operations(
                       operation_id,account_id,operation_kind,idempotency_key_hash,
                       request_fingerprint,resource_id)
                   VALUES($1,$2,$3,$4,$5,$6) RETURNING *""",
                uuid.uuid4(), account_uuid, operation_kind, key_hash,
                request_fingerprint, resource_id,
            )
        return _operation(row)

    @staticmethod
    async def finalize_resource_on(
        connection: Any, *, operation_kind: str, resource_id: str,
        target: str, reason: str | None = None,
    ) -> bool:
        if target not in {"charged", "released"}:
            raise ValueError("unsupported quota final state")
        if target == "released" and not (reason or "").strip():
            raise ValueError("release reason is required")
        row = await connection.fetchrow(
            """UPDATE ai_usage_operations
               SET state=$3,finalized_at=now(),updated_at=now(),
                   release_reason=CASE WHEN $3='released' THEN $4 ELSE NULL END
               WHERE operation_kind=$1 AND resource_id=$2 AND state='reserved'
               RETURNING operation_id""",
            operation_kind, resource_id, target, reason,
        )
        return row is not None

    async def account_for_session_token(self, token: str) -> str | None:
        from backend.shared.auth import hash_session_token

        value = await self._pool.fetchval(
            """SELECT a.account_id FROM owner_session_tokens t
               JOIN anonymous_owners o USING(owner_id)
               JOIN accounts a ON a.account_id=o.account_id
               WHERE t.session_token_hash=$1 AND a.status='active'""",
            hash_session_token(token),
        )
        return str(value) if value else None

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
            """SELECT a.ai_request_limit,a.ai_quota_unlimited,
                      COALESCE(sum(o.units) FILTER (WHERE o.state='charged'),0) AS charged,
                      COALESCE(sum(o.units) FILTER (WHERE o.state='reserved'),0) AS reserved
               FROM accounts a LEFT JOIN ai_usage_operations o USING(account_id)
               WHERE a.account_id=$1 GROUP BY a.account_id""", uuid.UUID(account_id),
        )
        if row is None:
            raise AccountUnavailable
        unlimited = bool(row["ai_quota_unlimited"])
        limit = None if unlimited else int(row["ai_request_limit"])
        charged, reserved = int(row["charged"]), int(row["reserved"])
        return AccountUsage(
            unlimited=unlimited, limit=limit, charged=charged, reserved=reserved,
            remaining=None if unlimited else max(0, limit - charged - reserved),
        )

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

    async def recover_stale_reservations(
        self, *, before: datetime, limit: int = 100,
    ) -> dict[str, int]:
        """Reconcile only reservations whose authoritative work is terminal.

        Queued/running conversation jobs remain reserved. A stale synchronous
        proposal in ``generating`` has no surviving lease, so it is made
        explicitly retryable and released.
        """
        counts = {"charged": 0, "released": 0, "retained": 0}
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                rows = await connection.fetch(
                    """SELECT * FROM ai_usage_operations
                       WHERE state='reserved' AND reserved_at < $1
                       ORDER BY reserved_at,operation_id LIMIT $2
                       FOR UPDATE SKIP LOCKED""",
                    before, limit,
                )
                for operation in rows:
                    resource_id = operation["resource_id"]
                    target = reason = None
                    if operation["operation_kind"] == "conversation":
                        status = await connection.fetchval(
                            "SELECT status FROM jobs WHERE job_id=$1::uuid",
                            resource_id,
                        ) if resource_id else None
                        if status == "completed":
                            target = "charged"
                        elif status == "failed" or status is None:
                            target, reason = "released", "authoritative_job_not_chargeable"
                    else:
                        status = await connection.fetchval(
                            "SELECT status FROM personal_terms WHERE term_id=$1",
                            resource_id,
                        ) if resource_id else None
                        if status in {"proposed", "active", "deleted"}:
                            target = "charged"
                        elif status == "generating":
                            await connection.execute(
                                """UPDATE personal_terms SET status='failed',
                                   generation_error_code='interrupted',updated_at=now()
                                   WHERE term_id=$1 AND status='generating'""",
                                resource_id,
                            )
                            target, reason = "released", "interrupted_personal_term_generation"
                        elif status == "failed" or status is None:
                            target, reason = "released", "authoritative_proposal_not_chargeable"
                    if target is None:
                        counts["retained"] += 1
                        continue
                    changed = await connection.fetchrow(
                        """UPDATE ai_usage_operations
                           SET state=$2,finalized_at=now(),updated_at=now(),
                               release_reason=CASE WHEN $2='released' THEN $3 ELSE NULL END
                           WHERE operation_id=$1 AND state='reserved'
                           RETURNING operation_id""",
                        operation["operation_id"], target, reason,
                    )
                    counts[target] += int(changed is not None)
        return counts


def _operation(row: Any) -> QuotaOperation:
    data = dict(row)
    data["operation_id"] = str(data["operation_id"])
    data["account_id"] = str(data["account_id"])
    data.pop("idempotency_key_hash", None)
    return QuotaOperation(**data)
