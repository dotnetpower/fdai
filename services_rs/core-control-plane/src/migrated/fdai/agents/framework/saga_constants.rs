pub const AUDIT_OUTBOX_PENDING_SCAN_LIMIT: i64 = 5000;
pub const AUDIT_OUTBOX_MAINTENANCE_PAGE: i64 = 16;
pub const AUDIT_OUTBOX_TOMBSTONE_RETENTION: i64 = 1024;
pub const FORECAST_AUDIT_FENCE_SIZE: i64 = 10000;
pub const MAX_FINGERPRINT_INDEX: i64 = 50000;
pub const FINGERPRINT_RETENTION: i64 = 10000;
pub const MAX_HANDOFF_CONTEXT_ITEMS: i64 = 8;
pub const MAX_HANDOFF_CONTEXT_VALUE_CHARS: i64 = 256;

pub const FINGERPRINT_BUCKET: &str = "issue_fingerprint_index";
pub const AUDIT_OUTBOX_PREFIX: &str = "pantheon/saga/audit-outbox/";
pub const FINGERPRINT_PREFIX: &str = "pantheon/saga/issue-fingerprint/";
pub const ISSUE_CLOSE_ELIGIBILITY_PREFIX: &str = "pantheon/saga/issue-close-eligibility/";
pub const ISSUE_CLOSE_ELIGIBILITY_BUCKET: &str = "issue_close_eligibility";
