"""Owner-scoped persistence for personal term proposals and saved cards."""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

from backend.schemas.personal_terms import (
    PersonalTermDraft,
    PersonalTermGenerationRecord,
    PersonalTermRecord,
    PersonalTermUpdate,
)
from backend.shared.auth import hash_session_token


class PersonalTermNotFound(Exception):
    pass


class PersonalTermIdempotencyConflict(Exception):
    pass


class PersonalTermStateConflict(Exception):
    pass


EDITABLE_COLUMNS = {
    "role",
    "label_ko",
    "label_en",
    "plain_meaning_ko",
    "reference_checkpoints_ko",
    "cautions_ko",
    "aliases_ko",
    "query_fragments_en",
    "proposal_kind",
    "uncertainty_ko",
}
JSON_COLUMNS = {
    "reference_checkpoints_ko",
    "cautions_ko",
    "aliases_ko",
    "query_fragments_en",
}


class PersonalTermRepository:
    def __init__(self, pool: Any) -> None:
        self._pool = pool

    async def create_proposal(
        self,
        token: str,
        draft: PersonalTermDraft,
        *,
        idempotency_key: str,
        input_hash: str,
    ) -> tuple[PersonalTermRecord, bool]:
        if not token or not idempotency_key.strip() or not input_hash.strip():
            raise ValueError("token, idempotency_key and input_hash are required")
        key_hash = _digest(idempotency_key)
        payload = draft.model_dump(mode="json")
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                owner_id = await _owner_id(connection, token, lock=True)
                if owner_id is None:
                    raise PersonalTermNotFound
                existing = await connection.fetchrow(
                    """SELECT * FROM personal_terms
                       WHERE owner_id=$1 AND idempotency_key_hash=$2""",
                    owner_id,
                    key_hash,
                )
                if existing is not None:
                    if existing["input_hash"] != input_hash:
                        raise PersonalTermIdempotencyConflict
                    return _record(existing), False

                personal_term_id = uuid.uuid4()
                row = await connection.fetchrow(
                    """INSERT INTO personal_terms(
                           personal_term_id, term_id, owner_id, status, role,
                           label_ko, label_en, plain_meaning_ko,
                           reference_checkpoints_ko, cautions_ko, aliases_ko,
                           query_fragments_en, source_input, proposal_kind,
                           uncertainty_ko, idempotency_key_hash, input_hash)
                       VALUES($1,$2,$3,'proposed',$4,$5,$6,$7,$8::jsonb,$9::jsonb,
                              $10::jsonb,$11::jsonb,$12,$13,$14,$15,$16)
                       RETURNING *""",
                    personal_term_id,
                    f"personal_{personal_term_id.hex}",
                    owner_id,
                    payload["role"],
                    payload["label_ko"],
                    payload["label_en"],
                    payload["plain_meaning_ko"],
                    json.dumps(payload["reference_checkpoints_ko"], ensure_ascii=False),
                    json.dumps(payload["cautions_ko"], ensure_ascii=False),
                    json.dumps(payload["aliases_ko"], ensure_ascii=False),
                    json.dumps(payload["query_fragments_en"], ensure_ascii=False),
                    payload["source_input"],
                    payload["proposal_kind"],
                    payload["uncertainty_ko"],
                    key_hash,
                    input_hash,
                )
                return _record(row), True

    async def begin_generation(
        self,
        token: str,
        source_input: str,
        *,
        idempotency_key: str,
        input_hash: str,
    ) -> tuple[PersonalTermGenerationRecord, bool]:
        if not token or not idempotency_key.strip() or not input_hash.strip():
            raise ValueError("token, idempotency_key and input_hash are required")
        key_hash = _digest(idempotency_key)
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                owner_id = await _owner_id(connection, token, lock=True)
                if owner_id is None:
                    raise PersonalTermNotFound
                existing = await connection.fetchrow(
                    "SELECT * FROM personal_terms WHERE owner_id=$1 AND idempotency_key_hash=$2",
                    owner_id,
                    key_hash,
                )
                if existing is not None:
                    if existing["input_hash"] != input_hash:
                        raise PersonalTermIdempotencyConflict
                    return _generation_record(existing), False
                personal_term_id = uuid.uuid4()
                row = await connection.fetchrow(
                    """INSERT INTO personal_terms(
                           personal_term_id, term_id, owner_id, status, source_input,
                           idempotency_key_hash, input_hash, generation_attempts)
                       VALUES($1,$2,$3,'generating',$4,$5,$6,1)
                       RETURNING *""",
                    personal_term_id,
                    f"personal_{personal_term_id.hex}",
                    owner_id,
                    source_input,
                    key_hash,
                    input_hash,
                )
                return _generation_record(row), True

    async def get_generation(
        self, token: str, idempotency_key: str
    ) -> PersonalTermGenerationRecord:
        row = await self._pool.fetchrow(
            """SELECT p.* FROM personal_terms p
               JOIN anonymous_owners o USING(owner_id)
               WHERE o.session_token_hash=$1 AND p.idempotency_key_hash=$2""",
            hash_session_token(token),
            _digest(idempotency_key),
        )
        if row is None:
            raise PersonalTermNotFound
        return _generation_record(row)

    async def retry_generation(self, token: str, term_id: str) -> PersonalTermGenerationRecord:
        row = await self._pool.fetchrow(
            """UPDATE personal_terms p
               SET status='generating', generation_attempts=generation_attempts+1,
                   generation_error_code=NULL, updated_at=now()
               FROM anonymous_owners o
               WHERE o.owner_id=p.owner_id AND o.session_token_hash=$1
                 AND p.term_id=$2 AND p.status='failed'
               RETURNING p.*""",
            hash_session_token(token),
            term_id,
        )
        if row is None:
            raise PersonalTermStateConflict
        return _generation_record(row)

    async def complete_generation(
        self, token: str, term_id: str, draft: PersonalTermDraft
    ) -> PersonalTermRecord:
        payload = draft.model_dump(mode="json")
        row = await self._pool.fetchrow(
            """UPDATE personal_terms p SET
                   status='proposed', role=$3, label_ko=$4, label_en=$5,
                   plain_meaning_ko=$6, reference_checkpoints_ko=$7::jsonb,
                   cautions_ko=$8::jsonb, aliases_ko=$9::jsonb,
                   query_fragments_en=$10::jsonb, proposal_kind=$11,
                   uncertainty_ko=$12, generation_error_code=NULL, updated_at=now()
               FROM anonymous_owners o
               WHERE o.owner_id=p.owner_id AND o.session_token_hash=$1
                 AND p.term_id=$2 AND p.status='generating'
               RETURNING p.*""",
            hash_session_token(token),
            term_id,
            payload["role"],
            payload["label_ko"],
            payload["label_en"],
            payload["plain_meaning_ko"],
            json.dumps(payload["reference_checkpoints_ko"], ensure_ascii=False),
            json.dumps(payload["cautions_ko"], ensure_ascii=False),
            json.dumps(payload["aliases_ko"], ensure_ascii=False),
            json.dumps(payload["query_fragments_en"], ensure_ascii=False),
            payload["proposal_kind"],
            payload["uncertainty_ko"],
        )
        if row is None:
            raise PersonalTermStateConflict
        return _record(row)

    async def fail_generation(
        self, token: str, term_id: str, error_code: str
    ) -> PersonalTermGenerationRecord:
        row = await self._pool.fetchrow(
            """UPDATE personal_terms p
               SET status='failed', generation_error_code=$3, updated_at=now()
               FROM anonymous_owners o
               WHERE o.owner_id=p.owner_id AND o.session_token_hash=$1
                 AND p.term_id=$2 AND p.status='generating'
               RETURNING p.*""",
            hash_session_token(token),
            term_id,
            error_code,
        )
        if row is None:
            raise PersonalTermStateConflict
        return _generation_record(row)

    async def list_terms(self, token: str, *, include_deleted: bool = False) -> list[PersonalTermRecord]:
        if not token:
            return []
        statuses = "('proposed','active','deleted')" if include_deleted else "('proposed','active')"
        rows = await self._pool.fetch(
            f"""SELECT p.* FROM personal_terms p
                JOIN anonymous_owners o USING(owner_id)
                WHERE o.session_token_hash=$1 AND p.status IN {statuses}
                ORDER BY p.created_at, p.personal_term_id""",
            hash_session_token(token),
        )
        return [_record(row) for row in rows]

    async def get_term(
        self, token: str, term_id: str, *, include_deleted: bool = False
    ) -> PersonalTermRecord:
        statuses = "('proposed','active','deleted')" if include_deleted else "('proposed','active')"
        row = await self._pool.fetchrow(
            f"""SELECT p.* FROM personal_terms p
                JOIN anonymous_owners o USING(owner_id)
                WHERE o.session_token_hash=$1 AND p.term_id=$2 AND p.status IN {statuses}""",
            hash_session_token(token),
            term_id,
        )
        if row is None:
            raise PersonalTermNotFound
        return _record(row)

    async def get_active_term(self, token: str, term_id: str) -> PersonalTermRecord:
        """Return only an active card owned by this anonymous profile."""
        row = await self._pool.fetchrow(
            """SELECT p.* FROM personal_terms p
               JOIN anonymous_owners o USING(owner_id)
               WHERE o.session_token_hash=$1 AND p.term_id=$2 AND p.status='active'""",
            hash_session_token(token),
            term_id,
        )
        if row is None:
            raise PersonalTermNotFound
        return _record(row)

    async def update_term(
        self, token: str, term_id: str, update: PersonalTermUpdate
    ) -> PersonalTermRecord:
        changes = update.model_dump(exclude_unset=True, mode="json")
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                current = await connection.fetchrow(
                    """SELECT p.* FROM personal_terms p
                       JOIN anonymous_owners o USING(owner_id)
                       WHERE o.session_token_hash=$1 AND p.term_id=$2
                         AND p.status IN ('proposed','active')
                       FOR UPDATE OF p""",
                    hash_session_token(token),
                    term_id,
                )
                if current is None:
                    raise PersonalTermNotFound
                if (
                    current["status"] == "active"
                    and "role" in changes
                    and changes["role"] != current["role"]
                ):
                    raise PersonalTermStateConflict

                assignments: list[str] = []
                values: list[Any] = [current["owner_id"], term_id]
                for column in sorted(changes):
                    if column not in EDITABLE_COLUMNS:
                        raise ValueError(f"field is not editable: {column}")
                    value = changes[column]
                    if column in JSON_COLUMNS:
                        value = json.dumps(value, ensure_ascii=False)
                        assignments.append(f"{column}=${len(values) + 1}::jsonb")
                    else:
                        assignments.append(f"{column}=${len(values) + 1}")
                    values.append(value)
                row = await connection.fetchrow(
                    f"""UPDATE personal_terms
                        SET {', '.join(assignments)}, updated_at=now()
                        WHERE owner_id=$1 AND term_id=$2
                        RETURNING *""",
                    *values,
                )
                return _record(row)

    async def confirm_term(self, token: str, term_id: str) -> PersonalTermRecord:
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                owner_id = await _owner_id(connection, token, lock=True)
                if owner_id is None:
                    raise PersonalTermNotFound
                row = await connection.fetchrow(
                    "SELECT * FROM personal_terms WHERE owner_id=$1 AND term_id=$2 FOR UPDATE",
                    owner_id,
                    term_id,
                )
                if row is None or row["status"] == "deleted":
                    raise PersonalTermNotFound
                if row["status"] == "active":
                    return _record(row)
                if row["status"] != "proposed":
                    raise PersonalTermStateConflict
                slot = row["layout_slot"]
                if slot is None:
                    slot = await connection.fetchval(
                        """SELECT COALESCE(MAX(layout_slot), -1) + 1 FROM personal_terms
                           WHERE owner_id=$1 AND role=$2""",
                        owner_id,
                        row["role"],
                    )
                updated = await connection.fetchrow(
                    """UPDATE personal_terms SET status='active', layout_slot=$3,
                              updated_at=now(), deleted_at=NULL, deleted_from_status=NULL
                       WHERE owner_id=$1 AND term_id=$2 RETURNING *""",
                    owner_id,
                    term_id,
                    slot,
                )
                return _record(updated)

    async def soft_delete(self, token: str, term_id: str) -> PersonalTermRecord:
        row = await self._pool.fetchrow(
            """UPDATE personal_terms p
               SET deleted_from_status=CASE WHEN p.status='deleted' THEN p.deleted_from_status ELSE p.status END,
                   status='deleted', deleted_at=COALESCE(p.deleted_at, now()), updated_at=now()
               FROM anonymous_owners o
               WHERE o.owner_id=p.owner_id AND o.session_token_hash=$1 AND p.term_id=$2
               RETURNING p.*""",
            hash_session_token(token),
            term_id,
        )
        if row is None:
            raise PersonalTermNotFound
        return _record(row)

    async def restore_term(self, token: str, term_id: str) -> PersonalTermRecord:
        row = await self._pool.fetchrow(
            """UPDATE personal_terms p
               SET status=COALESCE(p.deleted_from_status, 'proposed'), deleted_from_status=NULL,
                   deleted_at=NULL, updated_at=now()
               FROM anonymous_owners o
               WHERE o.owner_id=p.owner_id AND o.session_token_hash=$1
                 AND p.term_id=$2 AND p.status='deleted'
               RETURNING p.*""",
            hash_session_token(token),
            term_id,
        )
        if row is None:
            existing = await self.get_term(token, term_id, include_deleted=True)
            if existing.status != "deleted":
                return existing
            raise PersonalTermNotFound
        return _record(row)


async def _owner_id(connection, token: str, *, lock: bool = False):
    suffix = " FOR UPDATE" if lock else ""
    return await connection.fetchval(
        "SELECT owner_id FROM anonymous_owners WHERE session_token_hash=$1" + suffix,
        hash_session_token(token),
    )


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _record(row) -> PersonalTermRecord:
    payload = dict(row)
    for column in JSON_COLUMNS:
        if isinstance(payload.get(column), str):
            payload[column] = json.loads(payload[column])
    payload.pop("owner_id", None)
    payload.pop("idempotency_key_hash", None)
    payload.pop("input_hash", None)
    payload.pop("deleted_from_status", None)
    payload.pop("generation_error_code", None)
    return PersonalTermRecord.model_validate(payload)


def _generation_record(row) -> PersonalTermGenerationRecord:
    payload = dict(row)
    return PersonalTermGenerationRecord.model_validate({
        key: payload.get(key)
        for key in PersonalTermGenerationRecord.model_fields
    })
