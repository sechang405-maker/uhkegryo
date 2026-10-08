CREATE TABLE anonymous_owners (
    owner_id UUID PRIMARY KEY,
    session_token_hash TEXT NOT NULL UNIQUE,
    default_session_id UUID REFERENCES sessions(session_id) ON DELETE SET NULL
);
INSERT INTO anonymous_owners (owner_id, session_token_hash, default_session_id)
SELECT session_id, session_token_hash, session_id FROM sessions;
ALTER TABLE sessions ADD COLUMN owner_id UUID REFERENCES anonymous_owners(owner_id);
UPDATE sessions SET owner_id = session_id;
ALTER TABLE sessions ALTER COLUMN owner_id SET NOT NULL;
ALTER TABLE sessions DROP COLUMN session_token_hash;
ALTER TABLE sessions ADD COLUMN memory_json JSONB NOT NULL DEFAULT '{}';
CREATE INDEX sessions_owner_id_idx ON sessions(owner_id);
