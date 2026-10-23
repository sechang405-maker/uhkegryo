ALTER TABLE personal_terms
    ALTER COLUMN role DROP NOT NULL,
    ALTER COLUMN label_ko DROP NOT NULL,
    ALTER COLUMN label_en DROP NOT NULL,
    ALTER COLUMN plain_meaning_ko DROP NOT NULL,
    ALTER COLUMN reference_checkpoints_ko DROP NOT NULL,
    ALTER COLUMN cautions_ko DROP NOT NULL,
    ALTER COLUMN aliases_ko DROP NOT NULL,
    ALTER COLUMN query_fragments_en DROP NOT NULL,
    ALTER COLUMN proposal_kind DROP NOT NULL;

ALTER TABLE personal_terms
    ADD COLUMN generation_error_code TEXT;

ALTER TABLE personal_terms
    ADD CONSTRAINT personal_terms_payload_for_visible_state CHECK (
        status IN ('generating', 'failed') OR (
            role IS NOT NULL
            AND label_ko IS NOT NULL
            AND label_en IS NOT NULL
            AND plain_meaning_ko IS NOT NULL
            AND reference_checkpoints_ko IS NOT NULL
            AND cautions_ko IS NOT NULL
            AND aliases_ko IS NOT NULL
            AND query_fragments_en IS NOT NULL
            AND proposal_kind IS NOT NULL
        )
    );
