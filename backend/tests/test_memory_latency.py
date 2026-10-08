import asyncio
import json
import uuid
from types import SimpleNamespace

import pytest

from backend.services import conversation_context
from backend.services.job_repository import JobRepository
from backend.services.session_repository import SessionRepository
from backend.tests.test_conversation_memory import MemoryAdapter
from backend.tests.test_conversation_sessions import database_case


@pytest.mark.parametrize("text,fast", [
    ("마른 캐릭터가 서 있는 자세 레퍼런스를 찾아줘", True),
    ("Find character pose references", True),
    ("아까 추천한 포즈는?", False), ("추천했던 자세 이름은?", False),
    ("아까보다 팔을 높여줘", False), ("포즈만 앉은 모습으로 바꿔줘", False),
    ("앉은 자세로", False), ("이전에라는 단어가 적힌 캐릭터를 그려줘", False),
    ("What pose did you suggest?", False), ("지난번 결과와 같은 자세를 찾아줘", False),
    ("이 캐릭터를 더 자연스럽게", False),
])
def test_conservative_recall_gate(text, fast):
    assert conversation_context.is_clear_new_request(text, {"state": {}}) is fast
    assert not conversation_context.is_clear_new_request(text, {"state": {"pending_question": "어떤 자세인가요?"}})


def test_fast_path_preserves_context_without_classification():
    async def case():
        context = {"state": {"constraints": {"body": {"term_id": "slim"}}}}
        adapter = SimpleNamespace(memory=lambda *a, **k: pytest.fail("classify must not run"))
        result = await conversation_context.recall(None, {"request_text": "마른 캐릭터 자세를 찾아줘"},
                                                   context, adapter, None)
        assert result == (None, False)
        assert context["state"]["constraints"]["body"]["term_id"] == "slim"
    asyncio.run(case())


async def seed(pool):
    session = await SessionRepository(pool).create_session("summary-test")
    await pool.execute("""INSERT INTO jobs(job_id,session_id,request_text,request_text_hash,
        idempotency_key_hash,idempotency_expires_at,status,final_payload_json,created_at)
        SELECT gen_random_uuid(),$1::uuid,'서 있는 자세',md5(g::text),md5(g::text),
        now()+interval '10 minutes','completed','{"agent_status":"success"}'::jsonb,
        now()-interval '1 day'+g*interval '1 second' FROM generate_series(1,9) g""", session)
    return uuid.UUID(session)


def test_worker_fast_path_and_pending_question_keep_context(snapshot_factory, card_factory):
    async def case(pool):
        from backend.services.agent_worker import AgentJobWorker
        session = await SessionRepository(pool).create_session("routing-test")
        jobs, adapter = JobRepository(pool), MemoryAdapter()
        operations = []
        original = adapter.memory
        async def counted(operation, *args, **kwargs):
            operations.append(operation)
            return await original(operation, *args, **kwargs)
        adapter.memory = counted
        worker = AgentJobWorker(pool, snapshot_factory([card_factory("pose_standing")]), adapter=adapter)
        for _ in range(2):
            await jobs.submit(session_id=session, request_text="캐릭터가 서 있는 자세를 찾아줘", idempotency_key=str(uuid.uuid4()))
            assert await worker.run_once()
        assert operations == [] and adapter.contexts[1]["constraints"]["pose"]["term_id"] == "pose_standing"
        await pool.execute("UPDATE sessions SET memory_json=memory_json || $2::jsonb WHERE session_id=$1",
                           uuid.UUID(session), json.dumps({"pending_question": "어떤 자세를 원하시나요?"}))
        await jobs.submit(session_id=session, request_text="서 있는 자세", idempotency_key=str(uuid.uuid4()))
        assert await worker.run_once()
        assert operations == ["classify"] and adapter.contexts[-1]["pending_question"] == "어떤 자세를 원하시나요?"
    asyncio.run(database_case(case))
