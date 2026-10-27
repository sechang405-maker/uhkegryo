CREATE TABLE portfolio_llm_daily_usage (
    usage_date DATE PRIMARY KEY,
    used_calls SMALLINT NOT NULL CHECK (used_calls BETWEEN 0 AND 40),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE portfolio_llm_daily_usage IS
    'UTC-day atomic reservations for actual external LLM calls in portfolio mode.';
