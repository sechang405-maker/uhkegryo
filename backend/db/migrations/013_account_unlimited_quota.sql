ALTER TABLE accounts
    ADD COLUMN ai_quota_unlimited BOOLEAN NOT NULL DEFAULT FALSE;

COMMENT ON COLUMN accounts.ai_quota_unlimited IS
    'Explicit per-account application quota policy; provider limits still apply.';
