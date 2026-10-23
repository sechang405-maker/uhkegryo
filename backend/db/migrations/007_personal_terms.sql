CREATE TABLE personal_terms (
    personal_term_id UUID PRIMARY KEY,
    term_id TEXT NOT NULL UNIQUE CHECK (term_id ~ '^personal_[0-9a-f]{32}$'),
    owner_id UUID NOT NULL REFERENCES anonymous_owners(owner_id) ON DELETE CASCADE,
    status TEXT NOT NULL CHECK (status IN ('generating', 'proposed', 'active', 'deleted', 'failed')),
    role TEXT NOT NULL CHECK (role IN ('body', 'pose', 'composition', 'perspective')),
    label_ko TEXT NOT NULL CHECK (char_length(btrim(label_ko)) BETWEEN 1 AND 120),
    label_en TEXT NOT NULL CHECK (char_length(btrim(label_en)) BETWEEN 1 AND 120),
    plain_meaning_ko TEXT NOT NULL CHECK (char_length(btrim(plain_meaning_ko)) BETWEEN 1 AND 1000),
    reference_checkpoints_ko JSONB NOT NULL DEFAULT '[]' CHECK (jsonb_typeof(reference_checkpoints_ko) = 'array'),
    cautions_ko JSONB NOT NULL DEFAULT '[]' CHECK (jsonb_typeof(cautions_ko) = 'array'),
    aliases_ko JSONB NOT NULL DEFAULT '[]' CHECK (jsonb_typeof(aliases_ko) = 'array'),
    query_fragments_en JSONB NOT NULL DEFAULT '[]' CHECK (jsonb_typeof(query_fragments_en) = 'array'),
    source_input TEXT NOT NULL CHECK (char_length(btrim(source_input)) BETWEEN 1 AND 300),
    proposal_kind TEXT NOT NULL CHECK (proposal_kind IN ('descriptive', 'coined', 'ambiguous')),
    uncertainty_ko TEXT CHECK (uncertainty_ko IS NULL OR char_length(btrim(uncertainty_ko)) BETWEEN 1 AND 1000),
    layout_slot INTEGER CHECK (layout_slot IS NULL OR layout_slot >= 0),
    idempotency_key_hash TEXT NOT NULL,
    input_hash TEXT NOT NULL,
    generation_attempts INTEGER NOT NULL DEFAULT 0 CHECK (generation_attempts >= 0),
    deleted_from_status TEXT CHECK (deleted_from_status IS NULL OR deleted_from_status IN ('proposed', 'active', 'failed')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ
);

CREATE UNIQUE INDEX personal_terms_owner_idempotency_idx
    ON personal_terms(owner_id, idempotency_key_hash);
CREATE UNIQUE INDEX personal_terms_owner_role_slot_idx
    ON personal_terms(owner_id, role, layout_slot) WHERE layout_slot IS NOT NULL;
CREATE INDEX personal_terms_owner_status_idx
    ON personal_terms(owner_id, status, created_at, personal_term_id);
