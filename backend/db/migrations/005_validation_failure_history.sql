ALTER TABLE jobs ADD COLUMN IF NOT EXISTS validation_failure_history_json JSONB NOT NULL DEFAULT '{}'::jsonb;
