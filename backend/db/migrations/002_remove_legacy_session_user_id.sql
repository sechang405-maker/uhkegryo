-- Anonymous sessions are identified by session_token_hash, without login accounts.
ALTER TABLE sessions DROP COLUMN IF EXISTS user_id;
