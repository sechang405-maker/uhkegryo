CREATE TABLE IF NOT EXISTS sessions (
    session_id UUID PRIMARY KEY,
    session_token_hash TEXT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_activity_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS jobs (
    job_id UUID PRIMARY KEY,
    session_id UUID NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    request_text TEXT NOT NULL,
    request_text_hash TEXT NOT NULL,
    idempotency_key_hash TEXT NOT NULL,
    idempotency_expires_at TIMESTAMPTZ NOT NULL,
    status TEXT NOT NULL,
    attempt INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    lease_expires_at TIMESTAMPTZ,
    next_retry_at TIMESTAMPTZ DEFAULT NULL,
    succeeded BOOLEAN,
    final_payload_json JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS jobs_session_id_idx ON jobs(session_id);
