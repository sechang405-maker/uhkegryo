import asyncio
import json
import uuid
from pathlib import Path

import pytest

from backend.services import agent_worker
from backend.services.job_repository import JobRepository, StaleJobAttempt
from backend.services.session_repository import SessionRepository
from backend.schemas.models import AgentResult
from backend.schemas.models import InterpretationOutput, InterpretationSelection
from backend.schemas.memory import RecallQuery, RecallAnswer, ContextUpdate
from backend.tests.test_conversation_sessions import database_case


def test_memory_answer_contract():
    assert "memory_answer" in AgentResult.model_fields
    result = AgentResult(agent_status="memory_answer", memory_answer="이 대화 기록에서 해당 내용을 확인할 수 없습니다.")
    assert result.reference_plan is None
    with pytest.raises(ValueError):
        AgentResult(agent_status="memory_answer", memory_answer="날씬한 체형을 추천했어요.")


def test_adapter_supports_context_and_memory_operations():
    import inspect
    from backend.services.llm import LLMInterpretationAdapter
    assert "session_context" in inspect.signature(LLMInterpretationAdapter.interpret).parameters
    assert hasattr(LLMInterpretationAdapter, "memory")


def test_context_isolated_and_completion_atomic():
    async def case(pool):
        from backend.services.conversation_memory import ConversationMemory
        sessions, jobs = SessionRepository(pool), JobRepository(pool)
        a, b = await sessions.create_session("a"), await sessions.create_session("a")
        created, _ = await jobs.submit(session_id=a, request_text="마른 체형", idempotency_key=str(uuid.uuid4()))
        job = await jobs.claim_next()
        memory = ConversationMemory(pool)
        context = await memory.load(job)
        assert context["recent"] == []
        await jobs.update_status(job_id=created.job_id, status=agent_worker.JobStatus.VALIDATING, attempt=1)
        await jobs.update_status(job_id=created.job_id, status=agent_worker.JobStatus.RENDERING, attempt=1)
        answer = AgentResult(agent_status="memory_answer", memory_answer="이 대화 기록에서 해당 내용을 확인할 수 없습니다.")
        with pytest.raises(StaleJobAttempt):
            await memory.complete(dict(job) | {"attempt": 99}, answer, {"pending_question": "wrong"})
        assert json.loads(await pool.fetchval("SELECT memory_json FROM sessions WHERE session_id=$1", uuid.UUID(a))) == {}
        await memory.complete(job, answer, {"pending_question": "saved"})
        assert (await jobs.get(session_id=a, job_id=created.job_id)).result.memory_answer
        await jobs.submit(session_id=b, request_text="다른 대화", idempotency_key=str(uuid.uuid4()))
        other = await jobs.claim_next()
        assert (await memory.load(other))["recent"] == []
    asyncio.run(database_case(case))


def test_memory_adapter_keeps_history_in_user_message(monkeypatch):
    from backend.tests.test_llm_adapter import _adapter, _FakeCompletions, _FakeResponse, REPO_PROMPT_FILE
    completions = _FakeCompletions([_FakeResponse('{"mode":"recall","latest":true}')])
    adapter = _adapter(completions)
    monkeypatch.setattr(adapter, "_resolve_prompt_path", lambda: REPO_PROMPT_FILE)
    response = asyncio.run(adapter.memory("classify", {
        "request_text": "아까 포즈는?", "session_context": {"recent": [{"request_text": "untrusted_marker"}]},
    }, RecallQuery, job_id=str(uuid.uuid4()), session_id=str(uuid.uuid4()), attempt=1, max_attempts=3))
    assert response.mode == "recall"
    messages = completions.calls[0]["messages"]
    assert [message["role"] for message in messages] == ["system", "user"]
    assert "untrusted_marker" not in messages[0]["content"]
    assert "untrusted_marker" in messages[1]["content"]


class MemoryAdapter:
    def __init__(self):
        self.contexts = []
        self.recall = False
        self.memory_operations = []

    async def memory(self, operation, data, output_type, **trace):
        self.memory_operations.append(operation)
        assert operation in ("classify", "answer")
        if operation == "classify":
            return RecallQuery(mode="recall" if self.recall else "none", role="pose", latest=True)
        item = data["records"][0]
        return RecallAnswer(answer="서 있는 자세를 추천했어요.", citations=[
            {"job_id": item["job_id"], "quote": "서 있는"}])

    async def interpret(self, text, **kwargs):
        self.contexts.append(kwargs["session_context"])
        return InterpretationOutput(interpretation_state="select_terms",
            selections=[InterpretationSelection(role="pose", term_id="pose_standing",
                         evidence=["서 있는"], confidence=0.9)],
            context_updates=[ContextUpdate(role="pose", term_id="pose_standing", evidence="서 있는")])


def test_worker_remembers_recent_records_and_recalls(snapshot_factory, card_factory):
    async def case(pool):
        jobs, adapter = JobRepository(pool), MemoryAdapter()
        snapshot = snapshot_factory([card_factory("pose_standing", label_ko="서 있는 자세")])
        worker = agent_worker.AgentJobWorker(pool, snapshot, adapter=adapter)
        session_id = await SessionRepository(pool).create_session("user")
        for i in range(9):
            await jobs.submit(session_id=session_id, request_text=f"{i} 서 있는 자세", idempotency_key=str(uuid.uuid4()))
            assert await worker.run_once()
        assert adapter.contexts[1]["constraints"]["pose"]["term_id"] == "pose_standing"
        assert len(adapter.contexts[-1]["recent"]) == 6
        assert "summarize" not in adapter.memory_operations
        adapter.recall = True
        submitted, _ = await jobs.submit(session_id=session_id, request_text="아까 추천한 포즈는?", idempotency_key=str(uuid.uuid4()))
        await worker.run_once()
        result = (await jobs.get(session_id=session_id, job_id=submitted.job_id)).result
        assert result.agent_status == "memory_answer"
        assert result.sources[0].href.startswith("/api/jobs/")
        assert len(adapter.contexts) == 9
        assert await pool.fetchval("SELECT count(*) FROM jobs") == 10
    asyncio.run(database_case(case))


def test_worker_uses_recent_records_without_summary_in_long_history(snapshot_factory, card_factory):
    async def case(pool):
        session = await SessionRepository(pool).create_session("owner")
        await pool.execute("""INSERT INTO jobs(job_id,session_id,request_text,request_text_hash,
            idempotency_key_hash,idempotency_expires_at,status,final_payload_json,created_at)
            SELECT gen_random_uuid(),$1::uuid,'서 있는 자세',md5(g::text),md5(g::text),
            now()+interval '10 minutes','completed','{"agent_status":"success"}'::jsonb,
            now()-interval '1 day'+g*interval '1 second' FROM generate_series(1,110) g""", session)
        jobs, adapter = JobRepository(pool), MemoryAdapter()
        worker = agent_worker.AgentJobWorker(pool, snapshot_factory([
            card_factory("pose_standing", label_ko="서 있는 자세")]), adapter=adapter)
        new, _ = await jobs.submit(session_id=session, request_text="서 있는 자세", idempotency_key=str(uuid.uuid4()))
        assert await worker.run_once()
        assert "summarize" not in adapter.memory_operations
        assert len(adapter.contexts[0]["recent"]) == 6
        assert set(adapter.contexts[0]) == {"constraints", "pending_question", "recent", "sources"}
        assert (await jobs.get(session_id=session, job_id=new.job_id)).job_status == "completed"

    asyncio.run(database_case(case))


@pytest.mark.parametrize("bad", ["quote", "inactive", "duplicate", "foreign"])
def test_invalid_context_cannot_change_memory(snapshot_factory, card_factory, bad):
    from backend.services import conversation_context
    from backend.services.llm import LLMInvalidStructuredOutput
    async def case(pool):
        from backend.services.conversation_memory import ConversationMemory
        session = await SessionRepository(pool).create_session("a")
        jobs = JobRepository(pool)
        await jobs.submit(session_id=session, request_text="서 있는 자세", idempotency_key=str(uuid.uuid4()))
        job = await jobs.claim_next()
        selection = InterpretationSelection(role="pose", term_id="pose_standing", evidence=["서 있는"], confidence=.9)
        updates = [ContextUpdate(role="pose", term_id="pose_standing", evidence="서 있는")]
        if bad == "quote":
            selection.evidence = ["날아다니는"]
        elif bad == "inactive":
            updates[0].term_id = "pose_unknown"
        elif bad == "duplicate":
            updates *= 2
        else:
            selection.source_job_id = uuid.uuid4()
        output = InterpretationOutput(interpretation_state="select_terms", selections=[selection], context_updates=updates)
        with pytest.raises(LLMInvalidStructuredOutput):
            await conversation_context.validate(ConversationMemory(pool), job, output,
                snapshot_factory([card_factory("pose_standing")]))
        assert json.loads(await pool.fetchval("SELECT memory_json FROM sessions WHERE session_id=$1", uuid.UUID(session))) == {}
    asyncio.run(database_case(case))


def test_recall_filters_and_foreign_sources(snapshot_factory, card_factory):
    from backend.services.conversation_memory import ConversationMemory, record
    from backend.services.llm import LLMInvalidStructuredOutput
    async def case(pool):
        sessions, jobs = SessionRepository(pool), JobRepository(pool)
        a, b = await sessions.create_session("a"), await sessions.create_session("b")
        worker = agent_worker.AgentJobWorker(pool, snapshot_factory([
            card_factory("pose_standing", label_en="standing-only-label")]), adapter=MemoryAdapter())
        first, _ = await jobs.submit(session_id=a, request_text="서 있는 자세", idempotency_key=str(uuid.uuid4()))
        await worker.run_once()
        await jobs.submit(session_id=b, request_text="다른 대화", idempotency_key=str(uuid.uuid4()))
        other = await jobs.claim_next()
        memory = ConversationMemory(pool)
        with pytest.raises(LLMInvalidStructuredOutput):
            await memory.records(other, [first.job_id])
        await jobs.submit(session_id=a, request_text="전에 추천은?", idempotency_key=str(uuid.uuid4()))
        job = await pool.fetchrow("SELECT * FROM jobs WHERE session_id=$1 ORDER BY created_at DESC LIMIT 1", uuid.UUID(a))
        assert len(await memory.search(job, RecallQuery(mode="recall", keywords=["서 있는"]))) == 1
        assert not await memory.search(job, RecallQuery(mode="recall", keywords=["없는 내용"]))
        assert len(await memory.search(job, RecallQuery(mode="recall", keywords=["standing-only-label"]))) == 1
        row = await pool.fetchrow("SELECT * FROM jobs WHERE job_id=$1", uuid.UUID(first.job_id))
        payload = json.loads(row["final_payload_json"])
        payload["reference_plan"]["terms"][0]["pins"] = [{"thumbnail_url": "private-thumbnail", "pin_url": "private-pin"}]
        clean = record(dict(row) | {"final_payload_json": payload})
        assert "private-" not in json.dumps(clean)
    asyncio.run(database_case(case))


def test_mixed_request_still_interprets_when_recall_is_empty(snapshot_factory, card_factory):
    async def case(pool):
        class Mixed(MemoryAdapter):
            async def memory(self, operation, data, output_type, **kwargs):
                if operation == "classify":
                    return RecallQuery(mode="mixed", keywords=["없는 기록"])
                return await super().memory(operation, data, output_type, **kwargs)
        adapter, jobs = Mixed(), JobRepository(pool)
        session = await SessionRepository(pool).create_session("owner")
        worker = agent_worker.AgentJobWorker(pool, snapshot_factory([card_factory("pose_standing")]), adapter=adapter)
        new, _ = await jobs.submit(session_id=session, request_text="지난 추천은? 이번에는 서 있는 자세",
                                   idempotency_key=str(uuid.uuid4()))
        await worker.run_once()
        result = (await jobs.get(session_id=session, job_id=new.job_id)).result
        assert adapter.contexts
        assert result.reference_plan.terms[0].term_id == "pose_standing"
        assert result.memory_answer and not result.sources
    asyncio.run(database_case(case))


def test_eval27_followup_preserves_body_and_pending_question(snapshot_factory, card_factory):
    async def case(pool):
        class FollowupAdapter(MemoryAdapter):
            async def interpret(self, text, **kwargs):
                self.contexts.append(kwargs["session_context"])
                if text == "마른 체형 레퍼런스를 찾아줘":
                    return InterpretationOutput(interpretation_state="select_terms", selections=[
                        InterpretationSelection(role="body", term_id="body_slim", evidence=["마른 체형"], confidence=.9)],
                        context_updates=[ContextUpdate(role="body", term_id="body_slim", evidence="마른 체형")])
                if text == "마른 체형":
                    return InterpretationOutput(interpretation_state="needs_clarification",
                        clarification_type="insufficient_visual_evidence",
                        unresolved_constraints=["포즈"], clarifying_question="어떤 포즈인가요?",
                        context_updates=[ContextUpdate(role="body", term_id=None, evidence=text)])
                term = "pose_standing" if text == "서 있는" else "pose_weight_shift"
                evidence = text if term == "pose_standing" else "한쪽 다리에 힘"
                return InterpretationOutput(interpretation_state="select_terms", selections=[
                    InterpretationSelection(role="pose", term_id=term, evidence=[evidence], confidence=.9)],
                    context_updates=[ContextUpdate(role="pose", term_id=term, evidence=evidence)])
        adapter, jobs = FollowupAdapter(), JobRepository(pool)
        snapshot = snapshot_factory([card_factory("body_slim", role="body"),
                                     card_factory("pose_standing"), card_factory("pose_weight_shift")])
        worker = agent_worker.AgentJobWorker(pool, snapshot, adapter=adapter)
        session = await SessionRepository(pool).create_session("user")
        await jobs.submit(session_id=session, request_text="마른 체형 레퍼런스를 찾아줘", idempotency_key=str(uuid.uuid4()))
        await worker.run_once()
        fixture = json.loads((Path(__file__).parents[2] / "evals/memory.jsonl").read_text(encoding="utf-8").splitlines()[0])
        assert fixture["id"] == "MEM-01"
        for text in fixture["turns"]:
            new, _ = await jobs.submit(session_id=session, request_text=text, idempotency_key=str(uuid.uuid4()))
            await worker.run_once()
        assert adapter.contexts[2]["pending_question"] == "캐릭터의 체형·포즈·시점 중 어떤 정보를 더 알려주실 수 있나요?"
        assert adapter.contexts[2]["constraints"]["body"]["term_id"] == "body_slim"
        assert adapter.contexts[3]["constraints"]["body"]["term_id"] == "body_slim"
        result = (await jobs.get(session_id=session, job_id=new.job_id)).result
        assert [term.term_id for term in result.reference_plan.terms] == ["body_slim", "pose_weight_shift"]
        state = json.loads(await pool.fetchval("SELECT memory_json FROM sessions WHERE session_id=$1", uuid.UUID(session)))
        assert state["constraints"]["body"]["term_id"] == "body_slim"
        assert state["constraints"]["pose"]["term_id"] == "pose_weight_shift"
    asyncio.run(database_case(case))


@pytest.mark.parametrize("mode", ["mixed", "forged", "too_many"])
def test_recall_decisions_preserve_source_boundary(snapshot_factory, card_factory, mode):
    from backend.services.conversation_memory import ConversationMemory
    from backend.services.conversation_context import recall, NO_RECORDS, TOO_MANY
    from backend.services.job_trace import JobTracer
    from backend.services.llm import LLMInvalidStructuredOutput
    async def case(pool):
        jobs, adapter = JobRepository(pool), MemoryAdapter()
        session = await SessionRepository(pool).create_session("user")
        worker = agent_worker.AgentJobWorker(pool, snapshot_factory([card_factory("pose_standing")]), adapter=adapter)
        for _ in range(21 if mode == "too_many" else 1):
            await jobs.submit(session_id=session, request_text="서 있는 자세", idempotency_key=str(uuid.uuid4()))
            await worker.run_once()
        await jobs.submit(session_id=session, request_text="전에 포즈는? 서 있는 자세로", idempotency_key=str(uuid.uuid4()))
        job = await jobs.claim_next()
        memory = ConversationMemory(pool)
        context = await memory.load(job)
        original = adapter.memory
        async def response(operation, data, output_type, **kwargs):
            if operation == "classify":
                return RecallQuery(mode="mixed" if mode == "mixed" else "recall", role="pose")
            if operation == "answer" and mode == "forged":
                return RecallAnswer(answer="다른 추천", citations=[{"job_id": uuid.uuid4(), "quote": "서 있는"}])
            return await original(operation, data, output_type, **kwargs)
        adapter.memory = response
        with JobTracer().attempt(job) as trace:
            if mode == "forged":
                with pytest.raises(LLMInvalidStructuredOutput):
                    await recall(memory, job, context, adapter, trace)
            else:
                result, only = await recall(memory, job, context, adapter, trace)
                assert only == (mode == "too_many")
                if mode == "too_many":
                    assert result.memory_answer == TOO_MANY and not result.sources
                else:
                    assert result.sources and context["sources"]
    asyncio.run(database_case(case))
