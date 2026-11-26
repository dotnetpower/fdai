pub const PUBLICATION_REPLAY_PAYLOAD_MAX_BYTES: i64 = 8192;
pub const PUBLICATION_CAS_ATTEMPTS: i64 = 8;
pub const PUBLICATION_RECOVERY_LIMIT: i64 = 5000;
pub const PUBLICATION_MAINTENANCE_PAGE: i64 = 16;
pub const FULL_SNAPSHOT_LIMIT: i64 = 128;
pub const MAX_KPI_SAMPLES: i64 = 512;

pub const INCIDENT_CORRELATION_DISABLED: &[&str] = &["none", "disabled"];
pub const DETECTION_READINESS_EVENT: &str = "detection.readiness.observed";
pub const STATE_KEY: &str = "pantheon/heimdall/sensing-state";
pub const EPISODE_PREFIX: &str = "pantheon/heimdall/sensing-state/episodes/";
pub const READINESS_PREFIX: &str = "pantheon/heimdall/sensing-state/readiness/";
pub const PENDING_READINESS_PREFIX: &str = "pantheon/heimdall/sensing-state/readiness-pending/";
pub const PUBLICATION_PREFIX: &str = "pantheon/heimdall/publications/";
pub const RULE_VALIDATION_TIMEOUT_SECONDS: f64 = 5.0;
