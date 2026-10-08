"""PostgreSQL-backed persistence for Agent jobs."""
from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

from backend.schemas import AgentResult, Failure, JobEnvelope
from backend.schemas.enums import AgentStatus, JobStatus
from backend.schemas.models import PROGRESS_POLL_AFTER_MS, RETRY_COUNT_MAX
from backend.services.session_repository import SessionRepository

IDEMPOTENCY_TTL_SECONDS = 10 * 60


class IdempotencyConflict(Exception):
    """The same session and key were reused for different request text."""


class JobNotFound(Exception):
    """The job does not exist or is not owned by the requesting session."""


class InvalidJobTransition(ValueError):
    """The requested job status transition is not allowed."""


class StaleJobAttempt(InvalidJobTransition):
    """The status write belongs to an attempt that no longer owns the Job."""


_ALLOWED_PREVIOUS_STATUSES = {
    JobStatus.VALIDATING: [JobStatus.RUNNING.value],
    JobStatus.SEARCHING: [JobStatus.VALIDATING.value],
    JobStatus.RENDERING: [JobStatus.SEARCHING.value, JobStatus.VALIDATING.value],
    JobStatus.COMPLETED: [JobStatus.RENDERING.value],
    JobStatus.FAILED: [
        JobStatus.RUNNING.value,
        JobStatus.VALIDATING.value,
        JobStatus.SEARCHING.value,
        JobStatus.RENDERING.value,
    ],
}
_ACTIVE_STATUSES = [
    JobStatus.RUNNING.value,
    JobStatus.VALIDATING.value,
    JobStatus.SEARCHING.value,
    JobStatus.RENDERING.value,
]


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class JobRepository:
    """Store jobs and enforce session-scoped idempotency in PostgreSQL."""

    def __init__(self, pool: Any) -> None:
        self._pool = pool

    async def claim_next(self) -> Any | None:
        """Claim the oldest eligible job without racing another worker."""
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                return await connection.fetchrow(
                    """
                    WITH candidate AS (
                        SELECT queued.job_id
                        FROM jobs AS queued
                        WHERE queued.status = 'queued'
                          AND EXISTS (SELECT 1 FROM sessions s WHERE s.session_id=queued.session_id
                                      AND s.last_activity_at + interval '3 months' > now())
                          AND queued.attempt < queued.max_attempts
                          AND (queued.next_retry_at IS NULL OR queued.next_retry_at <= now())
                          AND NOT EXISTS (
                              SELECT 1 FROM jobs AS earlier
                              WHERE earlier.session_id = queued.session_id
                                AND earlier.status NOT IN ('completed', 'failed')
                                AND (earlier.created_at, earlier.job_id)
                                    < (queued.created_at, queued.job_id)
                          )
                        ORDER BY queued.created_at, queued.job_id
                        LIMIT 1
                        FOR UPDATE OF queued SKIP LOCKED
                    )
                    UPDATE jobs AS claimed
                    SET status = 'running',
                        attempt = claimed.attempt + 1,
                        lease_expires_at = now() + interval '30 seconds',
                        updated_at = now()
                    FROM candidate
                    WHERE claimed.job_id = candidate.job_id
                    RETURNING claimed.*
                    """
                )

    async def extend_lease(self, *, job_id: str, attempt: int) -> None:
        """Extend only the active lease owned by this claimed attempt."""
        row = await self._pool.fetchrow(
            """
            UPDATE jobs
            SET lease_expires_at = now() + interval '30 seconds', updated_at = now()
            WHERE job_id = $1::uuid
              AND attempt = $2
              AND status = ANY($3::text[])
            RETURNING job_id
            """,
            job_id,
            attempt,
            _ACTIVE_STATUSES,
        )
        if row is None:
            raise StaleJobAttempt

    async def submit(
        self, *, session_id: str, request_text: str, idempotency_key: str
    ) -> tuple[JobEnvelope, bool]:
        """Create a queued job or return its unexpired idempotent match."""
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                return await self._submit(
                    connection,
                    session_id=session_id,
                    request_text=request_text,
                    idempotency_key=idempotency_key,
                )

    async def submit_new_session(
        self, *, session_token: str, request_text: str, idempotency_key: str
    ) -> tuple[JobEnvelope, bool]:
        """Create a session and its first job atomically."""
        if not session_token:
            raise ValueError("session_token must not be empty")
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                session_id = await SessionRepository.ensure_session(connection, session_token)
                return await self._submit(
                    connection,
                    session_id=session_id,
                    request_text=request_text,
                    idempotency_key=idempotency_key,
                )

    async def _submit(
        self,
        connection: Any,
        *,
        session_id: str,
        request_text: str,
        idempotency_key: str,
    ) -> tuple[JobEnvelope, bool]:
        key_hash = _hash(idempotency_key)
        text_hash = _hash(request_text)
        await connection.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended($1, 0))",
            session_id,
        )
        live = await connection.fetchval(
            """UPDATE sessions SET last_activity_at=now()
               WHERE session_id=$1::uuid AND last_activity_at + interval '3 months' > now()
               RETURNING session_id""", session_id,
        )
        if live is None:
            raise JobNotFound
        existing = await connection.fetchrow(
            """
            SELECT * FROM jobs
            WHERE session_id = $1::uuid
              AND idempotency_key_hash = $2
              AND idempotency_expires_at > now()
            ORDER BY created_at DESC
            LIMIT 1
            """,
            session_id,
            key_hash,
        )
        if existing is not None:
            if existing["request_text_hash"] != text_hash:
                raise IdempotencyConflict
            return _to_envelope(existing), False

        row = await connection.fetchrow(
            """
            INSERT INTO jobs (
                job_id, session_id, request_text, request_text_hash,
                idempotency_key_hash, idempotency_expires_at, status,
                attempt, max_attempts, next_retry_at
            ) VALUES (
                $1::uuid, $2::uuid, $3, $4, $5,
                now() + interval '10 minutes', $6, 0, $7, NULL
            )
            RETURNING *
            """,
            str(uuid.uuid4()),
            session_id,
            request_text,
            text_hash,
            key_hash,
            JobStatus.QUEUED.value,
            RETRY_COUNT_MAX,
        )
        return _to_envelope(row), True

    async def get(self, *, session_id: str, job_id: str) -> JobEnvelope:
        row = await self._pool.fetchrow(
            """
            SELECT * FROM jobs
            WHERE job_id = $1::uuid AND session_id = $2::uuid
            """,
            job_id,
            session_id,
        )
        if row is None:
            raise JobNotFound
        return _to_envelope(row)

    async def update_status(
        self,
        *,
        job_id: str,
        status: JobStatus,
        attempt: int,
        result: AgentResult | None = None,
        failure: Failure | None = None,
    ) -> JobEnvelope:
        allowed_previous = _ALLOWED_PREVIOUS_STATUSES.get(status)
        if allowed_previous is None:
            raise InvalidJobTransition

        terminal = status in (JobStatus.COMPLETED, JobStatus.FAILED)
        if status is JobStatus.COMPLETED and (result is None or failure is not None):
            raise ValueError("completed job requires result and forbids failure")
        if status is JobStatus.FAILED and (failure is None or result is not None):
            raise ValueError("failed job requires failure and forbids result")
        if not terminal and (result is not None or failure is not None):
            raise ValueError("non-terminal job cannot have result or failure")
        if status is JobStatus.COMPLETED and result.agent_status in (AgentStatus.UNSAFE_INPUT, AgentStatus.OUT_OF_SCOPE):
            allowed_previous = [*allowed_previous, JobStatus.VALIDATING.value]

        row = await self._pool.fetchrow(
            """
            UPDATE jobs
            SET status = $2,
                succeeded = CASE WHEN $2 = 'completed' THEN TRUE
                                 WHEN $2 = 'failed' THEN FALSE ELSE NULL END,
                final_payload_json = CASE
                    WHEN $2 = 'completed' THEN $3::jsonb
                    WHEN $2 = 'failed' THEN $4::jsonb ELSE NULL END,
                updated_at = now(),
                completed_at = CASE WHEN $5 THEN now() ELSE NULL END,
                validation_feedback_json = CASE WHEN $5 THEN NULL ELSE validation_feedback_json END,
                lease_expires_at = CASE WHEN $5 THEN NULL ELSE lease_expires_at END
            WHERE job_id = $1::uuid
              AND status = ANY($6::text[])
              AND attempt = $7
            RETURNING *
            """,
            job_id,
            status.value,
            _dump(result) if result is not None else None,
            _dump(failure) if failure is not None else None,
            terminal,
            allowed_previous,
            attempt,
        )
        if row is None:
            current = await self._pool.fetchrow(
                "SELECT status, attempt FROM jobs WHERE job_id = $1::uuid", job_id
            )
            if current is None:
                raise JobNotFound
            if current["attempt"] != attempt:
                raise StaleJobAttempt
            raise InvalidJobTransition
        return _to_envelope(row)

    async def history(self, session_id: str, limit=20, offset=0) -> list[dict]:
        rows = await self._pool.fetch(
            """SELECT j.* FROM jobs j JOIN sessions s USING(session_id)
               WHERE j.session_id=$1::uuid AND s.last_activity_at + interval '3 months' > now()
               ORDER BY j.created_at,j.job_id LIMIT $2 OFFSET $3""", session_id, limit, offset,
        )
        return [dict(_to_envelope(row).model_dump(mode="json"),
                     request_text=row["request_text"], created_at=row["created_at"]) for row in rows]


def _dump(value: AgentResult | Failure) -> str:
    data = value.model_dump(mode="json")
    if isinstance(value, AgentResult):
        for term in (data.get("reference_plan") or {}).get("terms", []):
            for pin in term.get("pins", []):
                pin.pop("thumbnail_url", None)
    return json.dumps(data)


def _to_envelope(row: Any) -> JobEnvelope:
    status = JobStatus(row["status"])
    payload = row["final_payload_json"]
    if isinstance(payload, str):
        payload = json.loads(payload)
    succeeded = row["succeeded"]
    result = AgentResult.model_validate(payload) if succeeded is True else None
    failure = Failure.model_validate(payload) if succeeded is False else None
    terminal = status in (JobStatus.COMPLETED, JobStatus.FAILED)
    return JobEnvelope(
        job_id=str(row["job_id"]),
        session_id=str(row["session_id"]),
        job_status=status,
        attempt=max(1, row["attempt"]),
        max_attempts=row["max_attempts"],
        poll_after_ms=None if terminal else PROGRESS_POLL_AFTER_MS,
        result=result,
        failure=failure,
    )
