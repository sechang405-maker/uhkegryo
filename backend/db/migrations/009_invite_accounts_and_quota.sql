CREATE TABLE accounts (
    account_id UUID PRIMARY KEY,
    google_subject TEXT NOT NULL UNIQUE CHECK (btrim(google_subject) <> ''),
    email_normalized TEXT NOT NULL UNIQUE
        CHECK (email_normalized = lower(btrim(email_normalized)) AND email_normalized <> ''),
    display_name TEXT,
    role TEXT NOT NULL DEFAULT 'user' CHECK (role IN ('user', 'admin')),
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'disabled')),
    ai_request_limit BIGINT NOT NULL DEFAULT 0 CHECK (ai_request_limit >= 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_login_at TIMESTAMPTZ
);

CREATE TABLE invites (
    invite_id UUID PRIMARY KEY,
    email_normalized TEXT NOT NULL UNIQUE
        CHECK (email_normalized = lower(btrim(email_normalized)) AND email_normalized <> ''),
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'accepted', 'revoked')),
    created_by_account_id UUID NOT NULL REFERENCES accounts(account_id) ON DELETE RESTRICT,
    accepted_by_account_id UUID UNIQUE REFERENCES accounts(account_id) ON DELETE RESTRICT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    accepted_at TIMESTAMPTZ,
    revoked_at TIMESTAMPTZ
);

ALTER TABLE anonymous_owners ALTER COLUMN session_token_hash DROP NOT NULL;
ALTER TABLE anonymous_owners ADD COLUMN account_id UUID UNIQUE REFERENCES accounts(account_id) ON DELETE RESTRICT;
ALTER TABLE anonymous_owners ADD CONSTRAINT anonymous_owners_identity_check
    CHECK ((session_token_hash IS NOT NULL) <> (account_id IS NOT NULL));

CREATE TABLE ai_usage_operations (
    operation_id UUID PRIMARY KEY,
    account_id UUID NOT NULL REFERENCES accounts(account_id) ON DELETE RESTRICT,
    operation_kind TEXT NOT NULL CHECK (operation_kind IN ('conversation', 'personal_term_proposal')),
    idempotency_key_hash TEXT NOT NULL,
    request_fingerprint TEXT NOT NULL CHECK (btrim(request_fingerprint) <> ''),
    resource_id TEXT,
    state TEXT NOT NULL DEFAULT 'reserved' CHECK (state IN ('reserved', 'charged', 'released')),
    units SMALLINT NOT NULL DEFAULT 1 CHECK (units = 1),
    reserved_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    finalized_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    release_reason TEXT,
    UNIQUE(account_id, operation_kind, idempotency_key_hash),
    CHECK (
        (state = 'reserved' AND finalized_at IS NULL AND release_reason IS NULL)
        OR (state = 'charged' AND finalized_at IS NOT NULL AND release_reason IS NULL)
        OR (state = 'released' AND finalized_at IS NOT NULL
            AND release_reason IS NOT NULL AND btrim(release_reason) <> '')
    )
);
CREATE INDEX ai_usage_operations_account_state_idx ON ai_usage_operations(account_id, state);
CREATE INDEX ai_usage_operations_recovery_idx ON ai_usage_operations(reserved_at, operation_id)
    WHERE state = 'reserved';

CREATE TABLE admin_audit_events (
    event_id UUID PRIMARY KEY,
    actor_account_id UUID NOT NULL REFERENCES accounts(account_id) ON DELETE RESTRICT,
    target_account_id UUID REFERENCES accounts(account_id) ON DELETE RESTRICT,
    action TEXT NOT NULL CHECK (action IN (
        'invite_created', 'quota_limit_changed', 'account_disabled', 'account_enabled'
    )),
    details_json JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX admin_audit_events_target_created_idx
    ON admin_audit_events(target_account_id, created_at, event_id);
