"""One-time invite code issuance, redemption, revocation and identity transfer."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from backend.schemas.demo_accounts import DemoAccountRecord, InviteRecord
from backend.services.demo_account_repository import AdminPermissionDenied, _account, _active_admin, _audit, _invite
from backend.shared.auth import hash_session_token


class InviteCodeInvalid(Exception):
    pass


class InviteCodeUnavailable(Exception):
    pass


class InviteRateLimited(Exception):
    pass


class TransferUnavailable(Exception):
    pass


@dataclass(frozen=True)
class IssuedInvite:
    raw_code: str
    record: InviteRecord


@dataclass(frozen=True)
class IdentityTransfer:
    transfer_id: str
    account_id: str
    status: str


class InviteCodeRepository:
    def __init__(
        self, pool: Any, *, pepper: str, attempt_limit: int = 5,
        attempt_window: timedelta = timedelta(minutes=15),
    ) -> None:
        if len(pepper) < 8:
            raise ValueError("invite code pepper is too short")
        if attempt_limit < 1 or attempt_window <= timedelta(0):
            raise ValueError("invite attempt policy must be positive")
        self._pool, self._pepper = pool, pepper.encode()
        self._attempt_limit, self._attempt_window = attempt_limit, attempt_window

    async def issue(
        self, actor_account_id: str, *, beneficiary_label: str, initial_limit: int = 0,
        expires_at: datetime | None = None, admin_note: str | None = None,
    ) -> IssuedInvite:
        label = beneficiary_label.strip()
        if not label or initial_limit < 0:
            raise ValueError("beneficiary label and non-negative initial limit are required")
        raw = secrets.token_urlsafe(24)
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                actor = await _active_admin(connection, actor_account_id)
                row = await connection.fetchrow(
                    """INSERT INTO invites(
                           invite_id,email_normalized,status,created_by_account_id,beneficiary_label,
                           code_hash,code_hint,initial_ai_request_limit,expires_at,admin_note)
                       VALUES($1,NULL,'pending',$2,$3,$4,$5,$6,$7,$8) RETURNING *""",
                    uuid.uuid4(), actor["account_id"], label, self._hash(raw), raw[-6:],
                    initial_limit, expires_at, (admin_note or "").strip() or None,
                )
                await _audit(connection, actor["account_id"], None, "invite_created", {
                    "invite_id": str(row["invite_id"]), "beneficiary_label": label,
                })
                return IssuedInvite(raw, _invite(row))

    async def list_for_admin(self, actor_account_id: str) -> list[InviteRecord]:
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                await _active_admin(connection, actor_account_id)
                rows = await connection.fetch(
                    """SELECT * FROM invites
                       ORDER BY created_at DESC,invite_id DESC"""
                )
        return [_invite(row) for row in rows]

    async def redeem(
        self, raw_code: str, *, google_subject: str, verified_email: str,
        display_name: str | None = None, attempt_scope: str | None = None,
    ) -> DemoAccountRecord:
        if len(raw_code) < 20:
            raise InviteCodeInvalid
        subject, email = google_subject.strip(), verified_email.strip().casefold()
        if not subject or "@" not in email:
            raise ValueError("verified Google identity is required")
        if attempt_scope:
            await self._record_attempt(attempt_scope)
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                await connection.execute(
                    "SELECT pg_advisory_xact_lock(hashtext($1))",
                    self._hash("google-subject:" + subject),
                )
                existing = await connection.fetchrow(
                    "SELECT * FROM accounts WHERE google_subject=$1 FOR UPDATE", subject,
                )
                invitation = await connection.fetchrow(
                    "SELECT * FROM invites WHERE code_hash=$1 FOR UPDATE", self._hash(raw_code),
                )
                if invitation is None:
                    raise InviteCodeInvalid
                if existing is not None:
                    if invitation["status"] == "redeemed" and invitation["accepted_by_account_id"] == existing["account_id"]:
                        return _account(existing)
                    raise InviteCodeUnavailable
                if (invitation["status"] != "pending"
                        or invitation["expires_at"] is not None and invitation["expires_at"] <= datetime.now(timezone.utc)):
                    raise InviteCodeUnavailable
                if await connection.fetchval("SELECT 1 FROM accounts WHERE email_normalized=$1", email):
                    raise InviteCodeUnavailable
                account_id = uuid.uuid4()
                row = await connection.fetchrow(
                    """INSERT INTO accounts(
                           account_id,google_subject,email_normalized,display_name,ai_request_limit,last_login_at)
                       VALUES($1,$2,$3,$4,$5,now()) RETURNING *""",
                    account_id, subject, email, display_name, invitation["initial_ai_request_limit"],
                )
                await connection.execute(
                    "INSERT INTO anonymous_owners(owner_id,account_id) VALUES($1,$2)", uuid.uuid4(), account_id,
                )
                await connection.execute(
                    """UPDATE invites SET status='redeemed',accepted_by_account_id=$2,accepted_at=now()
                       WHERE invite_id=$1""", invitation["invite_id"], account_id,
                )
                return _account(row)

    async def _record_attempt(self, scope: str) -> None:
        scope_hash = self._hash("redeem-scope:" + scope)
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                await connection.execute("SELECT pg_advisory_xact_lock(hashtext($1))", scope_hash)
                await connection.execute(
                    "DELETE FROM invite_redemption_attempts WHERE attempted_at<now()-$1::interval",
                    self._attempt_window * 4,
                )
                attempts = await connection.fetchval(
                    """SELECT count(*) FROM invite_redemption_attempts
                       WHERE scope_hash=$1 AND attempted_at>now()-$2::interval""",
                    scope_hash, self._attempt_window,
                )
                if attempts >= self._attempt_limit:
                    raise InviteRateLimited
                await connection.execute(
                    "INSERT INTO invite_redemption_attempts(attempt_id,scope_hash) VALUES($1,$2)",
                    uuid.uuid4(), scope_hash,
                )

    async def revoke(self, actor_account_id: str, invite_id: str, *, reason: str) -> InviteRecord:
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                actor = await _active_admin(connection, actor_account_id)
                row = await connection.fetchrow(
                    """UPDATE invites SET status='revoked',revoked_at=now()
                       WHERE invite_id=$1 AND status='pending' RETURNING *""", uuid.UUID(invite_id),
                )
                if row is None:
                    raise InviteCodeUnavailable
                await _audit(connection, actor["account_id"], None, "invite_revoked", {
                    "invite_id": invite_id, "reason": reason,
                })
                return _invite(row)

    async def request_identity_transfer(
        self, account_id: str, *, target_registration_token: str,
        ttl: timedelta = timedelta(minutes=15),
    ) -> IdentityTransfer:
        registration = await self._pool.fetchrow(
            """SELECT * FROM registration_sessions
               WHERE session_token_hash=$1 AND consumed_at IS NULL AND expires_at>now()""",
            hash_session_token(target_registration_token),
        )
        if registration is None:
            raise TransferUnavailable
        if await self._pool.fetchval(
            "SELECT 1 FROM accounts WHERE google_subject=$1 OR email_normalized=$2",
            registration["google_subject"], registration["email_normalized"],
        ):
            raise TransferUnavailable
        row = await self._pool.fetchrow(
            """INSERT INTO identity_transfer_requests(
                   transfer_id,account_id,target_registration_session_id,
                   target_google_subject,target_email_normalized,expires_at)
               VALUES($1,$2,$3,$4,$5,now()+$6::interval) RETURNING *""",
            uuid.uuid4(), uuid.UUID(account_id), registration["registration_session_id"],
            registration["google_subject"], registration["email_normalized"], ttl,
        )
        return IdentityTransfer(str(row["transfer_id"]), str(row["account_id"]), row["status"])

    async def approve_identity_transfer(self, actor_account_id: str, transfer_id: str) -> DemoAccountRecord:
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                actor = await _active_admin(connection, actor_account_id)
                transfer = await connection.fetchrow(
                    """SELECT t.* FROM identity_transfer_requests t
                       JOIN registration_sessions r
                         ON r.registration_session_id=t.target_registration_session_id
                       WHERE t.transfer_id=$1 AND t.status='pending' AND t.expires_at>now()
                         AND r.consumed_at IS NULL AND r.expires_at>now()
                       FOR UPDATE OF t,r""",
                    uuid.UUID(transfer_id),
                )
                if transfer is None:
                    raise TransferUnavailable
                if await connection.fetchval(
                    "SELECT 1 FROM accounts WHERE google_subject=$1 OR email_normalized=$2",
                    transfer["target_google_subject"], transfer["target_email_normalized"],
                ):
                    raise TransferUnavailable
                row = await connection.fetchrow(
                    """UPDATE accounts SET google_subject=$2,email_normalized=$3,updated_at=now()
                       WHERE account_id=$1 RETURNING *""",
                    transfer["account_id"], transfer["target_google_subject"], transfer["target_email_normalized"],
                )
                await connection.execute(
                    """UPDATE auth_sessions SET status='revoked',revoked_at=now()
                       WHERE account_id=$1 AND status='active'""", transfer["account_id"],
                )
                await connection.execute(
                    """UPDATE identity_transfer_requests
                       SET status='approved',approved_by_account_id=$2,approved_at=now()
                       WHERE transfer_id=$1""", transfer["transfer_id"], actor["account_id"],
                )
                await connection.execute(
                    """UPDATE registration_sessions SET consumed_at=now()
                       WHERE registration_session_id=$1""",
                    transfer["target_registration_session_id"],
                )
                await _audit(connection, actor["account_id"], transfer["account_id"],
                             "account_identity_transferred", {"transfer_id": str(transfer["transfer_id"])})
                return _account(row)

    def _hash(self, raw: str) -> str:
        return hmac.new(self._pepper, raw.encode(), hashlib.sha256).hexdigest()
