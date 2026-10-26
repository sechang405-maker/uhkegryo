ALTER TABLE invites DROP CONSTRAINT invites_status_check;
ALTER TABLE invites ALTER COLUMN email_normalized DROP NOT NULL;
ALTER TABLE invites ADD COLUMN beneficiary_label TEXT;
ALTER TABLE invites ADD COLUMN code_hash TEXT UNIQUE;
ALTER TABLE invites ADD COLUMN code_hint TEXT;
ALTER TABLE invites ADD COLUMN initial_ai_request_limit BIGINT NOT NULL DEFAULT 0
    CHECK (initial_ai_request_limit >= 0);
ALTER TABLE invites ADD COLUMN expires_at TIMESTAMPTZ;
UPDATE invites SET status='redeemed' WHERE status='accepted';
ALTER TABLE invites ADD CONSTRAINT invites_status_check
    CHECK (status IN ('pending', 'redeemed', 'revoked', 'expired'));
ALTER TABLE invites ADD CONSTRAINT invites_identity_check CHECK (
    (code_hash IS NOT NULL AND beneficiary_label IS NOT NULL AND code_hint IS NOT NULL)
    OR (code_hash IS NULL AND email_normalized IS NOT NULL)
);

CREATE TABLE oidc_flows (
    state_hash TEXT PRIMARY KEY,
    nonce TEXT NOT NULL,
    code_verifier TEXT NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    consumed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX oidc_flows_expiry_idx ON oidc_flows(expires_at);

CREATE TABLE registration_sessions (
    registration_session_id UUID PRIMARY KEY,
    session_token_hash TEXT NOT NULL UNIQUE,
    google_subject TEXT NOT NULL,
    email_normalized TEXT NOT NULL,
    display_name TEXT,
    expires_at TIMESTAMPTZ NOT NULL,
    consumed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE auth_sessions (
    auth_session_id UUID PRIMARY KEY,
    session_token_hash TEXT NOT NULL UNIQUE,
    account_id UUID NOT NULL REFERENCES accounts(account_id) ON DELETE RESTRICT,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'revoked')),
    expires_at TIMESTAMPTZ NOT NULL,
    revoked_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX auth_sessions_account_status_idx ON auth_sessions(account_id, status);
CREATE INDEX auth_sessions_expiry_idx ON auth_sessions(expires_at);

CREATE VIEW owner_session_tokens AS
SELECT owner_id,session_token_hash,default_session_id,retained
FROM anonymous_owners WHERE session_token_hash IS NOT NULL
UNION ALL
SELECT o.owner_id,s.session_token_hash,o.default_session_id,o.retained
FROM auth_sessions s JOIN anonymous_owners o ON o.account_id=s.account_id
JOIN accounts a ON a.account_id=s.account_id
WHERE s.status='active' AND s.expires_at>now() AND a.status='active';

CREATE TABLE invite_redemption_attempts (
    attempt_id UUID PRIMARY KEY,
    scope_hash TEXT NOT NULL,
    attempted_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX invite_redemption_attempts_scope_time_idx
    ON invite_redemption_attempts(scope_hash,attempted_at);

CREATE TABLE identity_transfer_requests (
    transfer_id UUID PRIMARY KEY,
    account_id UUID NOT NULL REFERENCES accounts(account_id) ON DELETE RESTRICT,
    target_registration_session_id UUID NOT NULL
        REFERENCES registration_sessions(registration_session_id) ON DELETE RESTRICT,
    target_google_subject TEXT NOT NULL,
    target_email_normalized TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'rejected', 'expired')),
    expires_at TIMESTAMPTZ NOT NULL,
    approved_by_account_id UUID REFERENCES accounts(account_id) ON DELETE RESTRICT,
    approved_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX identity_transfer_pending_subject_idx
    ON identity_transfer_requests(target_google_subject) WHERE status='pending';

ALTER TABLE admin_audit_events DROP CONSTRAINT admin_audit_events_action_check;
ALTER TABLE admin_audit_events ADD CONSTRAINT admin_audit_events_action_check CHECK (action IN (
    'invite_created', 'invite_revoked', 'quota_limit_changed', 'account_disabled',
    'account_enabled', 'account_identity_transferred'
));
