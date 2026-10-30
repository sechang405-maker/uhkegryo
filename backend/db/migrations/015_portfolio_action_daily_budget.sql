CREATE TABLE IF NOT EXISTS portfolio_action_daily_usage (
    usage_date date NOT NULL,
    resource text NOT NULL CHECK (resource ~ '^[a-z0-9_]+$'),
    used_actions integer NOT NULL CHECK (used_actions >= 0),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (usage_date, resource)
);
