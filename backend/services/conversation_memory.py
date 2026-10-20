"""Read only this conversation; commit memory with the authoritative job attempt."""
import json
from uuid import UUID

from backend.schemas.enums import JobStatus, Role
from backend.services.job_repository import JobRepository, StaleJobAttempt
from backend.services.llm import LLMInvalidStructuredOutput
from backend.services.session_memory import STATE_KEYS, source_ids

RECENT_LIMIT = 6
RECORD_LIMIT = 4000


def decode(value):
    return json.loads(value) if isinstance(value, str) else (value or {})


def record(row, *, include_recommendations=False):
    payload = decode(row["final_payload_json"])
    safe = row["status"] == "completed" and payload.get("agent_status") not in ("unsafe_input", "out_of_scope")
    result = {"job_id": str(row["job_id"]), "request_text": row["request_text"] if safe else "",
              "terms": [], "question": None, "message": ""}
    if safe:
        result["terms"] = [{key: str(term.get(key, ""))[:200]
                            for key in ("role", "term_id", "label_ko", "label_en")}
                           for term in (payload.get("reference_plan") or {}).get("terms", [])[:10]]
        result["question"] = (payload.get("clarifying_question") or "")[:500]
        result["message"] = (payload.get("answer_text") or payload.get("user_message") or "")[:1000]
        if include_recommendations and payload.get('recommendation_group'):
            from backend.schemas.models import RecommendationGroup
            result['recommendation_group'] = RecommendationGroup.model_validate(payload['recommendation_group']).model_dump(mode='json')
            result['recommendation_answer'] = (result['recommendation_group'].get('source_answer') or payload.get('answer_text') or '')[:4000]
        if include_recommendations and payload.get('recommendation_adoption'):
            from backend.schemas.models import RecommendationAdoption
            result['recommendation_adoption'] = RecommendationAdoption.model_validate(payload['recommendation_adoption']).model_dump(mode='json')
        for term in result["terms"]:
            term["role"] = Role(term["role"]).value
    # Retain whole fields: never cut serialized JSON or expose provider payloads.
    while not include_recommendations and len(json.dumps(result, ensure_ascii=False)) > RECORD_LIMIT and result["terms"]:
        result["terms"].pop()
    return result


def evidence_text(item):
    return "\n".join([item["request_text"], item.get("question") or "",
                      item.get("message") or ""] +
                     [term[key] for term in item["terms"] for key in ("label_ko", "label_en")])


def normalize_constraints(constraints):
    """Read historical role keys and current term keys into one card-indexed map."""
    return {value["term_id"]: {**value, "role": Role(value.get("role", key)).value}
            for key, value in constraints.items()}


class ConversationMemory:
    def __init__(self, pool):
        self.pool = pool

    async def load(self, job):
        memory = await self.pool.fetchval(
            """SELECT memory_json FROM sessions WHERE session_id=$1
               AND (retained OR last_activity_at + interval '3 months' > now())""", job["session_id"],
        )
        if memory is None:
            raise StaleJobAttempt
        stored = decode(memory)
        scope_id = stored.get('topic_scope_id')
        rows = await self.pool.fetch(
            """SELECT * FROM jobs WHERE session_id=$1 AND (created_at,job_id)<($2,$3)
               AND status IN ('completed','failed')
               AND ($4::uuid IS NULL OR (created_at,job_id)>=(SELECT created_at,job_id FROM jobs
                    WHERE session_id=$1 AND job_id=$4))
               ORDER BY created_at DESC,job_id DESC LIMIT 6""",
            job["session_id"], job["created_at"], job["job_id"], UUID(scope_id) if scope_id else None,
        )
        state = {key: stored[key] for key in STATE_KEYS if key in stored}
        state.setdefault('memory_version', 1)
        state["constraints"] = normalize_constraints(state.get("constraints", {}))
        pinned = list(dict.fromkeys([*(value["source_job_id"] for value in state["constraints"].values() if value.get('source_job_id')), *source_ids(state)]))
        sources = await self.records(job, pinned) if pinned else []
        previous = await self.pool.fetchval(
            """SELECT final_payload_json FROM jobs WHERE session_id=$1
               AND (created_at,job_id)<($2,$3) AND status='completed'
               AND final_payload_json->>'agent_status' IN ('success','partial_result')
               AND COALESCE(final_payload_json->'recommendation_adoption'->>'status','') <> 'search_failed'
               AND jsonb_typeof(final_payload_json->'reference_plan')='object'
               AND ($4::uuid IS NULL OR (created_at,job_id)>=(SELECT created_at,job_id FROM jobs
                    WHERE session_id=$1 AND job_id=$4))
               ORDER BY created_at DESC,job_id DESC LIMIT 1""",
            job["session_id"], job["created_at"], job["job_id"], UUID(scope_id) if scope_id else None,
        )
        from backend.schemas.models import AgentResult
        previous_result = AgentResult.model_validate(decode(previous)).model_dump(mode="json") if previous else {}
        return {"state": state, "recent": [record(r) for r in reversed(rows)],
                "sources": sources, "previous_result": previous_result}

    async def records(self, job, ids):
        rows = await self.pool.fetch(
            """SELECT * FROM jobs WHERE session_id=$1 AND job_id=ANY($2::uuid[])
               AND (created_at,job_id)<($3,$4) AND status='completed'
               AND final_payload_json->>'agent_status' NOT IN ('unsafe_input','out_of_scope')""",
            job["session_id"], [UUID(str(value)) for value in ids], job["created_at"], job["job_id"],
        )
        if len(rows) != len(set(str(value) for value in ids)):
            raise LLMInvalidStructuredOutput("기억의 출처가 현재 대화의 선행 기록에 없습니다")
        return [record(row, include_recommendations=True) for row in rows]

    async def search(self, job, query):
        if query.source_job_ids:
            await self.records(job, query.source_job_ids)
        rows = await self.pool.fetch(
            """SELECT j.* FROM jobs j WHERE session_id=$1 AND (created_at,job_id)<($2,$3)
               AND status='completed'
               AND final_payload_json->>'agent_status' NOT IN ('unsafe_input','out_of_scope','memory_answer')
               AND ($4::text IS NULL OR EXISTS(SELECT 1 FROM jsonb_array_elements(
                    COALESCE(final_payload_json->'reference_plan'->'terms','[]'::jsonb)) t
                    WHERE t->>'role'=$4 OR ($4='composition' AND t->>'role' IN ('view','layout'))))
               AND ($5::text IS NULL OR EXISTS(SELECT 1 FROM jsonb_array_elements(
                    COALESCE(final_payload_json->'reference_plan'->'terms','[]'::jsonb)) t
                    WHERE t->>'term_id'=$5))
               AND (cardinality($6::text[])=0 OR EXISTS(SELECT 1 FROM unnest($6::text[]) k
                    WHERE strpos(lower(request_text || ' ' ||
                      COALESCE(final_payload_json->>'user_message','') || ' ' ||
                      COALESCE(final_payload_json->>'answer_text','') || ' ' ||
                      COALESCE(final_payload_json->>'clarifying_question','') || ' ' ||
                      COALESCE((SELECT string_agg(COALESCE(t->>'label_ko','') || ' ' ||
                                                 COALESCE(t->>'label_en',''),' ')
                        FROM jsonb_array_elements(COALESCE(
                          final_payload_json->'reference_plan'->'terms','[]'::jsonb)) t),'')
                    ),lower(k))>0))
               AND ($7::timestamptz IS NULL OR created_at >= $7)
               AND ($8::timestamptz IS NULL OR created_at < $8)
               AND (cardinality($9::uuid[])=0 OR job_id=ANY($9))
               ORDER BY created_at DESC,job_id DESC LIMIT $10""",
            job["session_id"], job["created_at"], job["job_id"], query.role, query.term_id,
            query.keywords, query.start, query.end, query.source_job_ids, 1 if query.latest else 21,
        )
        return [record(row) for row in rows]

    async def complete(self, job, result, state):
        async with self.pool.acquire() as connection:
            async with connection.transaction():
                live = await connection.fetchval(
                    """SELECT session_id FROM sessions WHERE session_id=$1
                       AND (retained OR last_activity_at + interval '3 months' > now()) FOR UPDATE""",
                    job["session_id"],
                )
                if live is None:
                    raise StaleJobAttempt
                state = {key: state[key] for key in STATE_KEYS if key in state}
                state.setdefault('memory_version', 1)
                await JobRepository(connection).update_status(
                    job_id=str(job["job_id"]), attempt=job["attempt"],
                    status=JobStatus.COMPLETED, result=result,
                )
                await connection.execute("UPDATE sessions SET memory_json=memory_json || $2::jsonb WHERE session_id=$1",
                                         job["session_id"], json.dumps(state, ensure_ascii=False))
