"""Worker trace linkage, terminal outcomes, and privacy boundary."""
import asyncio
import json
from contextlib import contextmanager
from contextvars import ContextVar
from types import SimpleNamespace

import pytest

from backend.schemas.enums import InterpretationState, JobStatus, Role
from backend.schemas.models import InterpretationOutput, InterpretationSelection
from backend.services import agent_worker
from backend.services.agent_worker import AgentJobWorker
from backend.services.job_trace import JobTracer
from backend.services.llm import LLMTimeout, PromptConfigurationError, LLMInvalidStructuredOutput
from backend.tests.test_agent_worker import EmptyMemory
from backend.schemas.memory import RecallQuery


class FakeLangfuse:
    def __init__(self):
        self.records = []
        self.current = ContextVar("trace_id", default=None)

    def create_trace_id(self, *, seed):
        return f"trace:{seed}"

    @contextmanager
    def start_as_current_observation(self, *, as_type, name, **kwargs):
        trace_id = (kwargs.get("trace_context") or {}).get("trace_id") or self.current.get()
        record = {"name": name, "type": as_type, "trace_id": trace_id, **kwargs}
        self.records.append(record)
        token = self.current.set(trace_id)
        try:
            yield SimpleNamespace(update=lambda **changes: record.update(changes))
        finally:
            self.current.reset(token)


class FakeStore:
    def __init__(self, jobs):
        self.jobs = iter(jobs)
        self.writes = []

    async def claim_next(self):
        return next(self.jobs, None)

    async def update_status(self, *, status, attempt, **kwargs):
        self.writes.append((status, attempt))

    async def extend_lease(self, **kwargs):
        pass

    async def handle_attempt_failure(self, **kwargs):
        return True


class FailingTwiceAdapter:
    def __init__(self, client):
        self.client = client

    async def memory(self, *args, **kwargs):
        return RecallQuery(mode="none")

    async def interpret(self, request_text, *, attempt, **kwargs):
        if attempt < 3:
            raise LLMTimeout("private upstream response")
        with self.client.start_as_current_observation(
            as_type="generation", name="interpreter"
        ):
            return InterpretationOutput(
                interpretation_state=InterpretationState.SELECT_TERMS,
                selections=[InterpretationSelection(
                    role=Role.POSE, term_id="pose_shift", evidence=["자세"], confidence=0.9,
                )],
                unresolved_constraints=[],
            )


def _worker(monkeypatch, snapshot, store, adapter, tracer):
    monkeypatch.setattr(agent_worker, "JobRepository", lambda _pool: store)
    monkeypatch.setattr(agent_worker, "JobRetryRecovery", lambda _pool: store)
    monkeypatch.setattr(agent_worker, "ConversationMemory", lambda _pool: EmptyMemory(store))
    return AgentJobWorker(object(), snapshot, adapter=adapter, tracer=tracer)


def _job(attempt, job_id="job-1"):
    return {"job_id": job_id, "session_id": "session-1", "request_text": "자세",
            "attempt": attempt, "max_attempts": 3,
            "session_token": "private-token", "thumbnail_url": "https://private-thumbnail"}


def test_attempt_validation_diagnostics_survive_later_success():
    client = FakeLangfuse()
    tracer = JobTracer(client)
    with tracer.attempt(_job(1)) as trace:
        trace.failed(_job(1), LLMInvalidStructuredOutput("private exception",
            stage="conversation_validation", feedback=[{"path": ["private field"],
            "code": "selection_evidence_invalid", "input": "private value"}]))
    with tracer.attempt(_job(2)) as trace:
        trace.completed(SimpleNamespace(agent_status=SimpleNamespace(value="success"), reason_codes=[]))
    assert client.records[0]["metadata"]["validation_diagnostics"] == [{
        "stage": "conversation_validation", "path": ["unknown_field"],
        "code": "selection_evidence_invalid"}]
    assert client.records[0]["metadata"]["attempt"] == 1
    assert "validation_diagnostics" not in client.records[1]["metadata"]
    assert "private" not in json.dumps(client.records)


def test_standard_session_attribute_is_scoped_to_attempt(monkeypatch):
    import sys
    session = ContextVar("test_session", default=None)
    seen = []

    @contextmanager
    def propagate_attributes(*, session_id):
        token = session.set(session_id)
        try:
            yield
        finally:
            session.reset(token)

    monkeypatch.setitem(sys.modules, "langfuse", SimpleNamespace(
        propagate_attributes=propagate_attributes))

    class Client(FakeLangfuse):
        @contextmanager
        def start_as_current_observation(self, **kwargs):
            seen.append(session.get())
            with super().start_as_current_observation(**kwargs) as span:
                yield span

    tracer = JobTracer(Client())
    with tracer.attempt(_job(1)):
        with tracer._observation(name="interpretation"):
            assert session.get() == "session-1"
    assert seen == ["session-1", "session-1"]
    assert session.get() is None


def test_retry_attempts_share_trace_and_keep_private_fields_out(
    monkeypatch, snapshot_factory, card_factory
):
    client = FakeLangfuse()
    shutdown_calls = []
    def shutdown():
        shutdown_calls.append(len(client.records))
        raise RuntimeError("telemetry unavailable")
    client.shutdown = shutdown
    store = FakeStore([_job(attempt) for attempt in (1, 2, 3)])
    tracer = JobTracer(client, model="test-model", prompt_version="prompt-v0")
    snapshot = snapshot_factory([card_factory("pose_shift", role="pose")])
    worker = _worker(monkeypatch, snapshot, store, FailingTwiceAdapter(client), tracer)
    async def run():
        for _ in range(3):
            assert await worker.run_once()
        task = asyncio.create_task(worker.run_forever(concurrency=1))
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    asyncio.run(run())
    roots = [r for r in client.records if r["name"] == "agent-job-attempt"]
    assert len(roots) == 3
    assert shutdown_calls == [len(client.records)]
    assert {r["trace_id"] for r in client.records} == {"trace:job-1"}
    assert [r["metadata"]["attempt"] for r in roots] == [1, 2, 3]
    assert all(r["metadata"]["model"] == "test-model" for r in roots)
    assert all(r["metadata"]["prompt_version"] == "prompt-v0" for r in roots)
    assert [r["output"]["backoff_ms"] for r in roots] == [1000, 2000, None]
    assert [r["output"]["failure_code"] for r in roots] == [None, None, None]
    assert roots[-1]["output"]["agent_status"] == "success"
    assert [r["name"] for r in client.records if r["type"] == "generation"] == ["interpreter"]
    assert {r["name"] for r in client.records} >= {"validating", "searching", "rendering"}
    encoded = json.dumps(client.records)
    assert all(value not in encoded for value in (
        "private-token", "private-thumbnail", "private upstream response"
    ))


def test_terminal_failure_records_public_code_only(monkeypatch, snapshot_factory):
    class BrokenAdapter:
        async def memory(self, *args, **kwargs):
            return RecallQuery(mode="none")

        async def interpret(self, *args, **kwargs):
            raise PromptConfigurationError("secret prompt path")

    client = FakeLangfuse()
    store = FakeStore([_job(1, "job-2")])
    worker = _worker(monkeypatch, snapshot_factory([]), store, BrokenAdapter(), JobTracer(client))
    asyncio.run(worker.run_once())
    assert client.records[0]["output"] == {
        "job_status": "failed", "agent_status": None, "reason_codes": [],
        "failure_code": "CONFIGURATION_ERROR", "error_type": "configuration",
        "backoff_ms": None,
    }
    assert "secret prompt path" not in json.dumps(client.records)


def test_observation_failure_does_not_change_job(monkeypatch, snapshot_factory, card_factory):
    class BrokenLangfuse(FakeLangfuse):
        def start_as_current_observation(self, **kwargs):
            raise RuntimeError("telemetry unavailable")

    store = FakeStore([_job(3, "job-3")])
    snapshot = snapshot_factory([card_factory("pose_shift", role="pose")])
    worker = _worker(monkeypatch, snapshot, store, FailingTwiceAdapter(FakeLangfuse()),
                     JobTracer(BrokenLangfuse()))
    assert asyncio.run(worker.run_once())
    assert store.writes[-1][0] is JobStatus.COMPLETED
