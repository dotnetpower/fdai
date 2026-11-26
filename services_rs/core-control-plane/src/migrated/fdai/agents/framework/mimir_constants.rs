pub const MAX_QUARANTINE: i64 = 5000;
pub const MAX_PENDING_CANDIDATES: i64 = 5000;
pub const MAX_CATALOG_REVIEW_PACKAGES: i64 = 5000;
pub const MAX_ISSUE_FINGERPRINTS: i64 = 50000;
pub const GOVERNANCE_RECOVERY_PAGE: i64 = 128;
pub const RULE_GENERATION_RECEIPT_RETAIN: i64 = 5000;
pub const MAX_PROMOTION_PERSIST_QUEUE: i64 = 1024;
pub const MAX_PROMOTION_PERSIST_ATTEMPTS: i64 = 8;
pub const RULE_PUBLICATION_MAINTENANCE_PAGE: i64 = 16;
pub const MAX_MAINTENANCE_RECORDS: i64 = 128;

pub const OPERATIONAL_RULE_PREFIX: &str = "learned.operational.";
pub const RULE_GENERATION_RECEIPT_PREFIX: &str = "mimir:rule-generation-activation-result:";
pub const RULE_GENERATION_VALIDATION_PREFIX: &str = "mimir:rule-generation-validation-result:";
pub const RULE_GENERATION_COMMAND_PREFIX: &str = "mimir:rule-generation-activation-command:";
pub const GOVERNANCE_PREFIX: &str = "pantheon/mimir/governance";
pub const DEFAULT_PROVIDER_TIMEOUT_SECONDS: f64 = 5.0;
