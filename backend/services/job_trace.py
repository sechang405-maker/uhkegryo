"""Langfuse Job trace boundary; only approved fields leave the worker."""
from __future__ import annotations

import json
import logging
import math
from time import perf_counter
from contextlib import contextmanager
from typing import Any, Iterator

from backend.services.job_retry_recovery import retry_delay_ms, should_retry, validation_diagnostics
from backend.services.llm import LLMError
from backend.services.failure_mapping import classify_failure

logger = logging.getLogger(__name__)


class JobTracer:
    def __init__(self, client: Any = None, *, model: str = "", prompt_version: str = ""):
        self.client = client
        self.model = model
        self.prompt_version = prompt_version

    def shutdown(self) -> None:
        try:
            if self.client is not None:
                self.client.shutdown()
        except Exception:
            logger.debug("Langfuse shutdown failed")

    @contextmanager
    def search(self, role: str, fragments: list[str], *, search_attempt: int | None = None) -> Iterator[Any]:
        with self._observation(
            name=f"pinterest-search-{role}", input={"role": role, "query_fragments": fragments},
            metadata={"role": role, "search_attempt": search_attempt},
        ) as span:
            try:
                yield span
            except BaseException as error:
                AttemptTrace._update(span, level="WARNING", status_message="search interrupted",
                                     output={"error_type": type(error).__name__})
                raise

    @contextmanager
    def phase(self, name: str, *, trace_context=None, **metadata):
        with self._observation(name=name, metadata=metadata, trace_context=trace_context) as span:
            started = perf_counter()
            metrics = {"status": "completed"}
            try:
                yield metrics
            except BaseException as error:
                metrics.update(status="interrupted", error_type=type(error).__name__)
                raise
            finally:
                metrics["elapsed_ms"] = round((perf_counter() - started) * 1000, 3)
                AttemptTrace._update(span, output=metrics,
                                     level="WARNING" if metrics["status"] == "interrupted" else "DEFAULT")

    @contextmanager
    def result_read(self, job_id: str, session_id: str):
        context = None
        if self.client is not None:
            try:
                context = {"trace_id": self.client.create_trace_id(seed=job_id)}
            except Exception:
                logger.debug("Langfuse result trace ID unavailable")
        # Polling must not create observations; keep context for widget refresh.
        with self._session(session_id):
            yield {"status": "completed", "trace_context": context}

    @staticmethod
    def pin_counts(pins):
        available = sum(pin.status.value == "available" for pin in pins)
        return {"pin_count": len(pins), "available_count": available,
                "unavailable_count": len(pins) - available}

    @staticmethod
    def search_result(span: Any, attempts: Any) -> None:
        engines = {"google images": "!goi", "duckduckgo images": "!ddi", "pinterest": "!pin"}
        reasons = {None, "access_denied", "suspended", "captcha", "rate_limited",
                   "timeout", "upstream_error", "malformed_response"}
        safe = []
        fields = ("engine", "bang", "latency_ms", "pin_count", "status", "failure_reason", "fallback")
        for row in attempts[:3] if isinstance(attempts, list) else []:
            if not isinstance(row, dict) or not all(key in row for key in fields):
                continue
            engine, elapsed, count = row.get("engine"), row.get("latency_ms"), row.get("pin_count")
            if (not isinstance(engine, str) or engine not in engines
                    or row.get("bang") != engines[engine]
                    or type(elapsed) not in (int, float) or not math.isfinite(elapsed) or elapsed < 0
                    or type(count) is not int or not 0 <= count <= 8
                    or row.get("status") not in ("success", "empty", "unavailable")
                    or not isinstance(row.get("failure_reason"), (str, type(None)))
                    or row.get("failure_reason") not in reasons
                    or type(row.get("fallback")) is not bool):
                continue
            safe.append({key: row[key] for key in fields})
        AttemptTrace._update(span, output={"engine_attempts": safe})

    @classmethod
    def from_settings(cls) -> "JobTracer":
        from backend.shared.config import get_settings

        settings = get_settings()
        client = None
        if settings.langfuse_public_key and settings.langfuse_secret_key:
            try:
                from langfuse import Langfuse

                client = Langfuse(
                    public_key=settings.langfuse_public_key,
                    secret_key=settings.langfuse_secret_key,
                    host=settings.langfuse_host,
                )
            except Exception:
                logger.debug("Langfuse client unavailable")
        return cls(
            client, model=settings.llm_model,
            prompt_version=settings.interpreter_prompt_version,
        )

    @contextmanager
    def attempt(self, job: Any) -> Iterator["AttemptTrace"]:
        job_id = str(job["job_id"])
        trace_id = None
        if self.client is not None:
            try:
                trace_id = self.client.create_trace_id(seed=job_id)
            except Exception:
                logger.debug("Langfuse trace ID unavailable")
        metadata = {
            "job_id": job_id,
            "session_id": str(job["session_id"]),
            "attempt": job["attempt"],
            "max_attempts": job["max_attempts"],
            "model": self.model,
            "prompt_version": self.prompt_version,
        }
        with self._session(str(job["session_id"])), self._observation(
            name="agent-job-attempt",
            input={"request_text": job["request_text"]},
            metadata=metadata,
            trace_context={"trace_id": trace_id} if trace_id else None,
        ) as span:
            yield AttemptTrace(self, span)

    @contextmanager
    def _session(self, session_id):
        context = None
        if self.client is not None:
            try:
                from langfuse import propagate_attributes
                context = propagate_attributes(session_id=session_id)
                context.__enter__()
            except Exception:
                context = None
                logger.debug("Langfuse session propagation unavailable")
        try:
            yield
        finally:
            if context is not None:
                try:
                    context.__exit__(None, None, None)
                except Exception:
                    logger.debug("Langfuse session propagation close unavailable")

    @contextmanager
    def _observation(self, **kwargs: Any) -> Iterator[Any]:
        if self.client is None:
            yield None
            return
        try:
            context = self.client.start_as_current_observation(as_type="span", **kwargs)
            span = context.__enter__()
        except Exception:
            logger.debug("Langfuse observation unavailable")
            yield None
            return
        try:
            yield span
        finally:
            try:
                context.__exit__(None, None, None)
            except Exception:
                logger.debug("Langfuse observation close failed")


class AttemptTrace:
    def __init__(self, tracer: JobTracer, span: Any):
        self._tracer = tracer
        self._span = span

    @contextmanager
    def stage(self, name: str) -> Iterator[None]:
        with self._tracer._observation(name=name) as span:
            try:
                yield
            except BaseException:
                self._update(span, level="WARNING", status_message="stage interrupted")
                raise

    def completed(self, result: Any) -> None:
        self._update(self._span, output={
            "job_status": "completed",
            "agent_status": result.agent_status.value,
            "reason_codes": [code.value for code in result.reason_codes],
            "failure_code": None,
            "error_type": None,
            "backoff_ms": None,
        })

    def failed(self, job: Any, error: Exception) -> None:
        retry = should_retry(job["attempt"], job["max_attempts"], error)
        code = classify_failure(error)
        diagnostics = validation_diagnostics(error)
        if diagnostics is not None:
            self._update(self._span, metadata={
                "job_id": str(job["job_id"]), "session_id": str(job["session_id"]),
                "attempt": job["attempt"], "max_attempts": job["max_attempts"],
                "model": self._tracer.model, "prompt_version": self._tracer.prompt_version,
                "validation_diagnostics": json.loads(diagnostics),
            })
        self._update(self._span, output={
            "job_status": "queued" if retry else "failed",
            "agent_status": None,
            "reason_codes": [],
            "failure_code": None if retry else code.value,
            "error_type": getattr(error, "error_type", "internal") if isinstance(error, LLMError) else "internal",
            "backoff_ms": retry_delay_ms(job["attempt"], error) if retry else None,
        })

    def stale(self) -> None:
        self._update(self._span, output={"job_status": "stale"})

    @staticmethod
    def _update(span: Any, **kwargs: Any) -> None:
        if span is not None:
            try:
                span.update(**kwargs)
            except Exception:
                logger.debug("Langfuse observation update failed")
