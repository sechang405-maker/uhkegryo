-- Additive flags; existing non-local retention behavior remains unchanged.
ALTER TABLE anonymous_owners ADD COLUMN retained BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE sessions ADD COLUMN retained BOOLEAN NOT NULL DEFAULT FALSE;
