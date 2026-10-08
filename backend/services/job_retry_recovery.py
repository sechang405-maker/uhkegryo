"""Schedule retryable Job failures and recover expired worker leases."""
from __future__ import annotations

import json
from typing import Any
from typing import get_args

from pydantic_core import ErrorType

from backend.schemas import Failure
from backend.schemas.enums import FailureCode, JobStatus
from backend.services.llm import LLMError, LLMInvalidStructuredOutput
from backend.services.failure_mapping import FAILURE_MESSAGE, public_failure
from backend.services.structured_output import response_format

_ACTIVE_STATUSES = [
    JobStatus.RUNNING.value,
    JobStatus.VALIDATING.value,
    JobStatus.SEARCHING.value,
    JobStatus.RENDERING.value,
]
_RETRYABLE_FAILURE_CODES = {
    FailureCode.LLM_TIMEOUT,
    FailureCode.LLM_RATE_LIMITED,
    FailureCode.LLM_UPSTREAM_UNAVAILABLE,
    FailureCode.LLM_INVALID_STRUCTURED_OUTPUT,
}
_FAILURE_MESSAGE = FAILURE_MESSAGE


def retry_delay_ms(attempt: int, error: Exception) -> int:
    """Return the contract backoff for the failed attempt."""
    retry_after_ms = getattr(error, "retry_after_ms", None)
    if getattr(error, "error_type", None) == "rate_limited" and retry_after_ms is not None:
        return min(max(int(retry_after_ms), 1_000), 30_000)
    return 1_000 if attempt == 1 else 2_000


def should_retry(attempt: int, max_attempts: int, error: Exception) -> bool:
    """Use the same retry decision for persistence and trace outcomes."""
    return (
        attempt < max_attempts
        and isinstance(error, LLMError)
        and error.retryable
        and error.failure_code in _RETRYABLE_FAILURE_CODES
    )


def _failure(error: Exception) -> Failure:
    return public_failure(error)


def validation_diagnostics(error: Exception) -> str | None:
    if not isinstance(error, LLMInvalidStructuredOutput):
        return None
    schema = response_format()["json_schema"]["schema"]
    fields = set(schema["properties"]) | {
        name for definition in schema.get("$defs", {}).values()
        for name in definition.get("properties", {})
    }
    codes = set(get_args(ErrorType)) | {
        "invalid_candidate", "role_duplicate", "role_order", "state_rules",
        "summary_source_invalid", "recall_citation_invalid", "selection_source_invalid",
        "selection_evidence_invalid", "context_evidence_invalid",
        "context_card_invalid", "selection_card_invalid",
    }
    stage = error.stage if error.stage in {
        "interpretation_schema", "memory_schema", "conversation_validation"
    } else "interpretation_schema"
    diagnostics = []
    for item in error.feedback[:8]:
        path = item.get("path", [])
        path = path[:8] if isinstance(path, list) else []
        diagnostics.append({
            "stage": stage,
            "path": [part if type(part) is int and 0 <= part < 10000 else
                     part if isinstance(part, str) and part in fields else "unknown_field" for part in path],
            "code": item.get("code") if item.get("code") in codes else "invalid_candidate",
        })
    return json.dumps(diagnostics)


class JobRetryRecovery:
    """Own retry scheduling and expired-lease recovery for PostgreSQL Jobs."""

    def __init__(self, pool: Any) -> None:
        self._pool = pool

    async def handle_attempt_failure(
        self,
        *,
        job_id: str,
        attempt: int,
        max_attempts: int,
        error: Exception,
    ) -> bool:
        if attempt < 1 or max_attempts < 1 or attempt > max_attempts:
            raise ValueError("attempt must be between 1 and max_attempts")

        async with self._pool.acquire() as connection:
            if should_retry(attempt, max_attempts, error):
                row = await connection.fetchrow(
                    """
                    UPDATE jobs
                    SET status = 'queued',
                        next_retry_at = now() + ($4::int * interval '1 millisecond'),
                        lease_expires_at = NULL,
                        succeeded = NULL,
                        final_payload_json = NULL,
                        validation_feedback_json = $6::jsonb,
                        validation_failure_history_json = CASE WHEN $7::jsonb IS NULL
                            THEN validation_failure_history_json
                            ELSE validation_failure_history_json || jsonb_build_object(($2::int)::text, $7::jsonb) END,
                        completed_at = NULL,
                        updated_at = now()
                    WHERE job_id = $1::uuid
                      AND status = ANY($5::text[])
                      AND attempt = $2
                      AND max_attempts = $3
                      AND attempt < max_attempts
                    RETURNING job_id
                    """,
                    job_id,
                    attempt,
                    max_attempts,
                    retry_delay_ms(attempt, error),
                    _ACTIVE_STATUSES,
                    json.dumps(error.feedback) if isinstance(error, LLMInvalidStructuredOutput) else None,
                    validation_diagnostics(error),
                )
            else:
                failure = _failure(error)
                row = await connection.fetchrow(
                    """
                    UPDATE jobs
                    SET status = 'failed',
                        next_retry_at = NULL,
                        lease_expires_at = NULL,
                        succeeded = FALSE,
                        final_payload_json = $4::jsonb,
                        validation_feedback_json = $6::jsonb,
                        validation_failure_history_json = CASE WHEN $7::jsonb IS NULL
                            THEN validation_failure_history_json
                            ELSE validation_failure_history_json || jsonb_build_object(($2::int)::text, $7::jsonb) END,
                        completed_at = now(),
                        updated_at = now()
                    WHERE job_id = $1::uuid
                      AND status = ANY($5::text[])
                      AND attempt = $2
                      AND max_attempts = $3
                    RETURNING job_id
                    """,
                    job_id,
                    attempt,
                    max_attempts,
                    json.dumps(failure.model_dump(mode="json")),
                    _ACTIVE_STATUSES,
                    validation_diagnostics(error),
                    validation_diagnostics(error),
                )
        return row is not None

    async def recover_expired_leases(self) -> dict[str, int]:
        interrupted = Failure(
            failure_code=FailureCode.JOB_INSTANCE_INTERRUPTED,
            user_message=_FAILURE_MESSAGE,
        )
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                failed = await connection.fetch(
                    """
                    UPDATE jobs
                    SET status = 'failed',
                        next_retry_at = NULL,
                        lease_expires_at = NULL,
                        succeeded = FALSE,
                        final_payload_json = $1::jsonb,
                        validation_feedback_json = NULL,
                        completed_at = now(),
                        updated_at = now()
                    WHERE status = ANY($2::text[])
                      AND lease_expires_at <= now()
                      AND attempt >= max_attempts
                    RETURNING job_id
                    """,
                    json.dumps(interrupted.model_dump(mode="json")),
                    _ACTIVE_STATUSES,
                )
                requeued = await connection.fetch(
                    """
                    UPDATE jobs
                    SET status = 'queued',
                        next_retry_at = NULL,
                        lease_expires_at = NULL,
                        succeeded = NULL,
                        final_payload_json = NULL,
                        completed_at = NULL,
                        updated_at = now()
                    WHERE status = ANY($1::text[])
                      AND lease_expires_at <= now()
                      AND attempt < max_attempts
                    RETURNING job_id
                    """,
                    _ACTIVE_STATUSES,
                )
        return {"requeued": len(requeued), "failed": len(failed)}
