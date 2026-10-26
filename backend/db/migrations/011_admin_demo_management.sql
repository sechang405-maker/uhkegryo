ALTER TABLE invites ADD COLUMN admin_note TEXT;

ALTER TABLE invites ADD CONSTRAINT invites_admin_note_length_check
    CHECK (admin_note IS NULL OR char_length(admin_note) <= 500);
