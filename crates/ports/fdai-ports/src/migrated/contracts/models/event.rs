use std::collections::BTreeMap;
#[derive(Clone, Debug, Default, PartialEq)]
pub struct Event {
    pub schema_version: String,
    pub event_id: String,
    pub idempotency_key: String,
    pub correlation_id: Option<String>,
    pub source: String,
    pub event_type: String,
    pub resource_ref: Option<String>,
    pub payload: BTreeMap<String, String>,
    pub detected_at: String,
    pub ingested_at: String,
    pub incident_correlation: String,
    pub tier: Option<String>,
    pub decision: Option<String>,
    pub mode: String,
}

pub const PUBLIC_EXPORTS: &[&str] = &["Event"];
