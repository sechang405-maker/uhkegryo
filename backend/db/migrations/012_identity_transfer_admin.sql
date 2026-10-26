CREATE UNIQUE INDEX identity_transfer_pending_account_idx
    ON identity_transfer_requests(account_id) WHERE status='pending';

ALTER TABLE admin_audit_events DROP CONSTRAINT admin_audit_events_action_check;
ALTER TABLE admin_audit_events ADD CONSTRAINT admin_audit_events_action_check CHECK (action IN (
    'invite_created', 'invite_revoked', 'quota_limit_changed', 'account_disabled',
    'account_enabled', 'account_identity_transferred', 'account_identity_transfer_rejected'
));
