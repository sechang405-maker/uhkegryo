import asyncio
import json
import uuid
from types import SimpleNamespace

import pytest

from backend.schemas.memory import RecallQuery
from backend.services import conversation_context
from backend.services.agent_worker import AgentJobWorker
from backend.services.conversation_memory import ConversationMemory
from backend.services.job_repository import JobRepository
from backend.services.llm import PromptConfigurationError
from backend.tests.test_conversation_memory import MemoryAdapter
from backend.tests.test_conversation_sessions import database_case
from backend.tests.test_llm_adapter import _adapter, _FakeCompletions, REPO_PROMPT_FILE
from backend.tests.test_memory_latency import seed


LEGACY = {"summary": "LEGACY_SUMMARY_MUST_NOT_REACH_LLM", "summary_sources": [str(uuid.uuid4())],
          "summary_input_hash": "old", "summary_truncated": True, "summarized_through": ["old", "old"],
          "summary_claim": {"token": "old", "expires_at": "2099-01-01T00:00:00+00:00"}}


def test_prepare_only_loads_context_and_prompt_ignores_legacy_summary():
    async def case():
        context = {"state": LEGACY | {"constraints": {}, "pending_question": "어떤 포즈인가요?"},
                   "recent": [], "sources": [], "summary_incomplete": True}
        async def load(job):
            return context
        def forbidden(*args):
            pytest.fail("summary candidate query or LLM ran")
        loaded = await conversation_context.prepare(SimpleNamespace(load=load, older=forbidden), {},
                                                    SimpleNamespace(memory=forbidden), None)
        assert loaded is context
        prompt = conversation_context.prompt_context(loaded)
        assert set(prompt) == {"constraints", "pending_question", "recent", "sources"}
        assert prompt["pending_question"] == "어떤 포즈인가요?"
        assert "summary" not in json.dumps(prompt)
    asyncio.run(case())


def test_summarize_operation_is_rejected_before_llm(monkeypatch):
    completions = _FakeCompletions()
    adapter = _adapter(completions)
    with pytest.raises(PromptConfigurationError):
        asyncio.run(adapter.memory("summarize", {}, RecallQuery))
    assert not completions.calls
    prompt = REPO_PROMPT_FILE.with_name("uhkegryo-interpreter-v4.md").read_text(encoding="utf-8")
    assert "## Memory summarize" not in prompt and "summary_incomplete" not in prompt


def test_pose_followup_preserves_body_question_and_legacy_data(snapshot_factory, card_factory):
    async def case(pool):
        session = await seed(pool)
        source = await pool.fetchval("SELECT job_id FROM jobs WHERE session_id=$1 ORDER BY created_at LIMIT 1", session)
        await pool.execute("UPDATE jobs SET request_text='마른 체형' WHERE job_id=$1", source)
        body = {"term_id": "body_slim", "evidence": "마른 체형", "source_job_id": str(source)}
        before = LEGACY | {"constraints": {"body": body}, "pending_question": "어떤 포즈인가요?"}
        await pool.execute("UPDATE sessions SET memory_json=$2::jsonb WHERE session_id=$1", session, json.dumps(before))
        adapter = MemoryAdapter()
        original = adapter.memory
        async def memory(operation, data, output_type, **kwargs):
            assert "LEGACY_SUMMARY" not in json.dumps(data)
            return await original(operation, data, output_type, **kwargs)
        adapter.memory = memory
        worker = AgentJobWorker(pool, snapshot_factory([card_factory("body_slim", role="body"),
                                                        card_factory("pose_standing")]), adapter=adapter)
        jobs = JobRepository(pool)
        request, _ = await jobs.submit(session_id=str(session), request_text="서 있는 자세", idempotency_key=str(uuid.uuid4()))
        assert await worker.run_once()
        assert (await jobs.get(session_id=str(session), job_id=request.job_id)).job_status == "completed"
        context = adapter.contexts[0]
        assert context["constraints"]["body"] == body
        assert context["pending_question"] == "어떤 포즈인가요?" and len(context["recent"]) == 6
        assert set(context) == {"constraints", "pending_question", "recent", "sources"}
        assert adapter.memory_operations == ["classify"]
        state = json.loads(await pool.fetchval("SELECT memory_json FROM sessions WHERE session_id=$1", session))
        assert state["constraints"]["body"] == body and state["constraints"]["pose"]["term_id"] == "pose_standing"
        assert state["pending_question"] is None
        assert {key: state[key] for key in LEGACY} == LEGACY
    asyncio.run(database_case(case))


def test_oldest_reference_is_recalled_after_40_turns_and_other_session_is_excluded(snapshot_factory, card_factory):
    async def case(pool):
        session = await seed(pool)
        await pool.execute("""INSERT INTO jobs(job_id,session_id,request_text,request_text_hash,
            idempotency_key_hash,idempotency_expires_at,status,final_payload_json,created_at)
            SELECT gen_random_uuid(),$1::uuid,'최근 서 있는 자세',md5('extra'||g::text),md5('extra'||g::text),
            now()+interval '10 minutes','completed','{"agent_status":"success"}'::jsonb,
            now()-interval '1 hour'+g*interval '1 second' FROM generate_series(1,31) g""", session)
        oldest = await pool.fetchval("SELECT job_id FROM jobs WHERE session_id=$1 ORDER BY created_at LIMIT 1", session)
        payload = {"agent_status": "success", "reference_plan": {"terms": [{
            "role": "pose", "term_id": "pose_standing", "label_ko": "서 있는 자세", "label_en": "Standing",
            "plain_meaning_ko": "서 있는 자세", "search_url": "https://www.pinterest.com/search/pins/?q=standing",
            "pins": [{"pin_id": "123", "pin_url": "https://www.pinterest.com/pin/123/", "status": "available"}]}]}}
        await pool.execute("UPDATE jobs SET request_text='초기 서 있는 자세',final_payload_json=$2::jsonb,succeeded=true WHERE job_id=$1",
                           oldest, json.dumps(payload))
        other = await seed(pool)
        await pool.execute("UPDATE jobs SET request_text='초기 서 있는 자세' WHERE session_id=$1", other)
        class Historical(MemoryAdapter):
            async def memory(self, operation, data, output_type, **kwargs):
                if operation == "classify":
                    assert len(data["session_context"]["recent"]) == 6
                    assert all(row["job_id"] != str(oldest) for row in data["session_context"]["recent"])
                    return RecallQuery(mode="recall", keywords=["초기"])
                assert operation == "answer" and [row["job_id"] for row in data["records"]] == [str(oldest)]
                return await super().memory(operation, data, output_type, **kwargs)
        jobs, adapter = JobRepository(pool), Historical()
        request, _ = await jobs.submit(session_id=str(session), request_text="초기에 서 있는 자세를 찾았지?",
                                       idempotency_key=str(uuid.uuid4()))
        worker = AgentJobWorker(pool, snapshot_factory([card_factory("pose_standing")]), adapter=adapter)
        assert await worker.run_once()
        result = (await jobs.get(session_id=str(session), job_id=request.job_id)).result
        assert result.agent_status == "memory_answer" and result.sources[0].job_id == oldest
        assert result.sources[0].href == "/api/jobs/" + str(oldest) and not adapter.contexts
        assert await pool.fetchval("SELECT count(*) FROM jobs WHERE session_id=$1", session) == 41
        assert json.loads(await pool.fetchval("SELECT final_payload_json FROM jobs WHERE job_id=$1", oldest)) == payload
        history = await jobs.history(str(session), limit=1)
        assert history[0]["result"]["reference_plan"]["terms"][0]["pins"][0]["pin_url"] == "https://www.pinterest.com/pin/123/"
        state = await ConversationMemory(pool).load(await pool.fetchrow("SELECT * FROM jobs WHERE job_id=$1", request.job_id))
        assert set(state["state"]) <= {"constraints", "pending_question"}
        assert state["previous_result"] == payload
        assert "oldest_recent" not in state
    asyncio.run(database_case(case))
