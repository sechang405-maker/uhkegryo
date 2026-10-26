"""One-time OIDC flows and hashed registration/application sessions."""

from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Any


class OIDCFlowUnavailable(Exception):
    pass


class AuthSessionUnavailable(Exception):
    pass


@dataclass(frozen=True)
class OIDCFlow:
    state: str
    nonce: str
    code_verifier: str


@dataclass(frozen=True)
class RegistrationIdentity:
    google_subject: str
    verified_email: str
    display_name: str | None


@dataclass(frozen=True)
class AuthenticatedAccount:
    account_id: str
    owner_id: str
    role: str
    status: str


class AuthSessionRepository:
    def __init__(self, pool: Any) -> None:
        self._pool = pool

    async def store_oidc_flow(self, state: str, nonce: str, code_verifier: str, *, ttl: timedelta) -> None:
        await self._pool.execute(
            """INSERT INTO oidc_flows(state_hash,nonce,code_verifier,expires_at)
               VALUES($1,$2,$3,now()+$4::interval)""",
            _digest(state), nonce, code_verifier, ttl,
        )

    async def consume_oidc_flow(self, state: str) -> OIDCFlow:
        row = await self._pool.fetchrow(
            """UPDATE oidc_flows SET consumed_at=now()
               WHERE state_hash=$1 AND consumed_at IS NULL AND expires_at>now()
               RETURNING nonce,code_verifier""", _digest(state),
        )
        if row is None:
            raise OIDCFlowUnavailable
        return OIDCFlow(state=state, nonce=row["nonce"], code_verifier=row["code_verifier"])

    async def create_registration_session(
        self, *, google_subject: str, verified_email: str, display_name: str | None,
        ttl: timedelta = timedelta(minutes=10),
    ) -> str:
        token = secrets.token_urlsafe(32)
        await self._pool.execute(
            """INSERT INTO registration_sessions(
                   registration_session_id,session_token_hash,google_subject,email_normalized,
                   display_name,expires_at)
               VALUES($1,$2,$3,$4,$5,now()+$6::interval)""",
            uuid.uuid4(), _digest(token), google_subject, verified_email.casefold(), display_name, ttl,
        )
        return token

    async def resolve_registration_session(self, token: str) -> RegistrationIdentity:
        row = await self._pool.fetchrow(
            """SELECT * FROM registration_sessions
               WHERE session_token_hash=$1 AND consumed_at IS NULL AND expires_at>now()""", _digest(token),
        )
        if row is None:
            raise AuthSessionUnavailable
        return RegistrationIdentity(row["google_subject"], row["email_normalized"], row["display_name"])

    async def consume_registration_session(self, token: str) -> None:
        result = await self._pool.execute(
            """UPDATE registration_sessions SET consumed_at=now()
               WHERE session_token_hash=$1 AND consumed_at IS NULL AND expires_at>now()""", _digest(token),
        )
        if result != "UPDATE 1":
            raise AuthSessionUnavailable

    async def create_app_session(self, account_id: str, *, ttl: timedelta = timedelta(days=30)) -> str:
        token = secrets.token_urlsafe(32)
        await self._pool.execute(
            """INSERT INTO auth_sessions(auth_session_id,session_token_hash,account_id,expires_at)
               VALUES($1,$2,$3,now()+$4::interval)""",
            uuid.uuid4(), _digest(token), uuid.UUID(account_id), ttl,
        )
        return token

    async def resolve_app_session(self, token: str) -> AuthenticatedAccount:
        row = await self._pool.fetchrow(
            """UPDATE auth_sessions s SET last_seen_at=now()
               FROM accounts a JOIN anonymous_owners o ON o.account_id=a.account_id
               WHERE s.session_token_hash=$1 AND s.account_id=a.account_id
                 AND s.status='active' AND s.expires_at>now() AND a.status='active'
               RETURNING a.account_id,o.owner_id,a.role,a.status""", _digest(token),
        )
        if row is None:
            raise AuthSessionUnavailable
        return AuthenticatedAccount(*(str(row[key]) for key in ("account_id", "owner_id")), row["role"], row["status"])

    async def revoke_app_session(self, token: str) -> None:
        await self._pool.execute(
            """UPDATE auth_sessions SET status='revoked',revoked_at=now()
               WHERE session_token_hash=$1 AND status='active'""", _digest(token),
        )


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
