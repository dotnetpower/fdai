pub const MAX_TRACKED_RESOURCES: i64 = 512;
pub const MAX_COST_EVIDENCE: i64 = 512;
pub const MAX_RETAINED_IDENTIFIER_CHARS: i64 = 128;

pub const RESOURCE_PREFIX: &str = "pantheon/freyr/capacity-resources/";
pub const ACCEPTED_PREFIX: &str = "pantheon/freyr/accepted-samples/";
pub const COST_PREFIX: &str = "pantheon/freyr/cost-evidence/";
pub const PUBLIC_EXPORTS: &[&str] = &["_ACCEPTED_PREFIX", "_COST_EVIDENCE_MAX_AGE", "_COST_PREFIX", "_MAX_COST_EVIDENCE", "_MAX_RETAINED_IDENTIFIER_CHARS", "_MAX_TRACKED_RESOURCES", "_RESOURCE_PREFIX"];
