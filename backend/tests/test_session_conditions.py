import asyncio
import json
import uuid

import pytest
import httpx

from backend.services.job_repository import JobNotFound
from backend.services.session_repository import SessionBusy, SessionRepository
from backend.tests.test_conversation_sessions import database_case


def _memory():
    return {
        "memory_version": 1,
        "constraints": {
            "pose_sitting": {
                "role": "pose",
                "term_id": "pose_sitting",
                "evidence": "앉아 있는 자세",
                "source_job_id": str(uuid.uuid4()),
            },
            "view_low_angle": {
                "role": "perspective",
                "term_id": "view_low_angle",
                "evidence": "로우 앵글",
                "source_job_id": str(uuid.uuid4()),
            },
        },
        "current_topic": {
            "scope_id": str(uuid.uuid4()),
            "terms": [
                {"role": "pose", "term_id": "pose_sitting", "evidence": "앉아 있는 자세"},
                {"role": "perspective", "term_id": "view_low_angle", "evidence": "로우 앵글"},
            ],
        },
        "excluded_conditions": {},
    }


def test_condition_removal_is_owner_scoped_idempotent_and_persistent():
    async def case(pool):
        repository = SessionRepository(pool)
        session_id = await repository.create_session("condition-owner")
        await pool.execute(
            "UPDATE sessions SET memory_json=$2::jsonb WHERE session_id=$1::uuid",
            session_id,
            json.dumps(_memory(), ensure_ascii=False),
        )

        before = await repository.get_condition_state("condition-owner", session_id)
        assert set(before["constraints"]) == {"pose_sitting", "view_low_angle"}

        after = await repository.remove_condition("condition-owner", session_id, "view_low_angle")
        assert set(after["constraints"]) == {"pose_sitting"}
        assert [term["term_id"] for term in after["current_topic"]["terms"]] == ["pose_sitting"]
        assert after["excluded_conditions"]["view_low_angle"]["role"] == "perspective"

        repeated = await repository.remove_condition("condition-owner", session_id, "view_low_angle")
        assert repeated == after
        stored = json.loads(await pool.fetchval(
            "SELECT memory_json FROM sessions WHERE session_id=$1::uuid", session_id
        ))
        assert stored == after

        with pytest.raises(JobNotFound):
            await repository.get_condition_state("other-owner", session_id)

    asyncio.run(database_case(case))


def test_condition_removal_rejects_an_inflight_answer_and_serializes_rapid_removals():
    async def case(pool):
        repository = SessionRepository(pool)
        session_id = await repository.create_session("rapid-owner")
        await pool.execute(
            "UPDATE sessions SET memory_json=$2::jsonb WHERE session_id=$1::uuid",
            session_id,
            json.dumps(_memory(), ensure_ascii=False),
        )
        await pool.execute(
            """INSERT INTO jobs(job_id,session_id,request_text,request_text_hash,
               idempotency_key_hash,idempotency_expires_at,status)
               VALUES($1,$2::uuid,'pending','hash','key',now(),'queued')""",
            uuid.uuid4(), session_id,
        )
        with pytest.raises(SessionBusy):
            await repository.remove_condition("rapid-owner", session_id, "pose_sitting")
        await pool.execute("UPDATE jobs SET status='failed' WHERE session_id=$1::uuid", session_id)

        first, second = await asyncio.gather(
            repository.remove_condition("rapid-owner", session_id, "pose_sitting"),
            repository.remove_condition("rapid-owner", session_id, "view_low_angle"),
        )
        stored = await repository.get_condition_state("rapid-owner", session_id)
        assert stored["constraints"] == {}
        assert stored["current_topic"] is None
        assert set(stored["excluded_conditions"]) == {"pose_sitting", "view_low_angle"}
        assert first != second

    asyncio.run(database_case(case))


def test_condition_api_returns_labels_requires_action_header_and_hides_foreign_session(
    monkeypatch, snapshot_factory, card_factory,
):
    from backend.main import app
    from backend.routes import agent
    from backend.services.job_repository import JobRepository

    async def case(pool):
        sessions = SessionRepository(pool)

        async def repositories():
            return sessions, JobRepository(pool)

        monkeypatch.setattr(agent, "get_repositories", repositories)
        monkeypatch.setattr(app.state, "catalog", snapshot_factory([
            card_factory("pose_sitting", role="pose", label_ko="앉기"),
            card_factory("view_low_angle", role="perspective", label_ko="로우 앵글"),
        ]), raising=False)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            created = await client.post("/api/sessions")
            session_id = created.json()["session_id"]
            await pool.execute(
                "UPDATE sessions SET memory_json=$2::jsonb WHERE session_id=$1::uuid",
                session_id, json.dumps(_memory(), ensure_ascii=False),
            )
            before = await client.get(f"/api/sessions/{session_id}/conditions")
            assert before.status_code == 200
            assert [item["label_ko"] for item in before.json()["items"]] == ["앉기", "로우 앵글"]

            denied = await client.delete(f"/api/sessions/{session_id}/conditions/view_low_angle")
            assert denied.status_code == 403
            removed = await client.delete(
                f"/api/sessions/{session_id}/conditions/view_low_angle",
                headers={"X-Conversation-Action": "remove-condition"},
            )
            assert removed.status_code == 200
            assert [item["term_id"] for item in removed.json()["items"]] == ["pose_sitting"]

            foreign = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
            try:
                await foreign.post("/api/sessions")
                hidden = await foreign.get(f"/api/sessions/{session_id}/conditions")
                assert hidden.status_code == 404
            finally:
                await foreign.aclose()

    asyncio.run(database_case(case))
