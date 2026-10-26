"""Storage records for invited demo accounts and cumulative AI usage."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class DemoAccountRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account_id: str
    google_subject: str
    email_normalized: str
    display_name: str | None = None
    role: Literal["user", "admin"]
    status: Literal["active", "disabled"]
    ai_request_limit: int
    created_at: datetime
    updated_at: datetime
    last_login_at: datetime | None = None


class InviteRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    invite_id: str
    email_normalized: str
    status: Literal["pending", "accepted", "revoked"]
    created_by_account_id: str
    accepted_by_account_id: str | None = None
    created_at: datetime
    accepted_at: datetime | None = None
    revoked_at: datetime | None = None


class QuotaOperation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation_id: str
    account_id: str
    operation_kind: Literal["conversation", "personal_term_proposal"]
    request_fingerprint: str
    resource_id: str | None = None
    state: Literal["reserved", "charged", "released"]
    units: int
    reserved_at: datetime
    finalized_at: datetime | None = None
    updated_at: datetime
    release_reason: str | None = None


class AccountUsage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    limit: int
    charged: int
    reserved: int
    remaining: int
