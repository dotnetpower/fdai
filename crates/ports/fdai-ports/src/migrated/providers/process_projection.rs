#[derive(Clone, Debug, Default, PartialEq)]
pub struct ProcessProjectionJob {
    pub event: String,
    pub attempts: i64,
    pub available_at: String,
    pub leased_until: Option<String>,
    pub last_error: Option<String>,
}

pub trait ProcessProjectionOutbox {
    fn claim_projections(&self, now: String, limit: i64, lease_seconds: i64) -> Vec<ProcessProjectionJob>;
    fn complete_projection(&self, event_id: String);
    fn retry_projection(&self, event_id: String, available_at: String, last_error: String);
}

pub const PUBLIC_EXPORTS: &[&str] = &["ProcessProjectionJob", "ProcessProjectionOutbox"];
