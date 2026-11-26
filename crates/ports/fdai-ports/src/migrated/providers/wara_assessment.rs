#[derive(Clone, Debug, Default, PartialEq)]
pub struct WaraReadPlan {
    pub recommendation_id: String,
    pub query_digest: String,
    pub evaluator_ref: String,
    pub evaluator_bindings_digest: String,
    pub workload_id: String,
    pub resource_ids: Vec<String>,
    pub provider_resource_types: Vec<String>,
    pub inventory_generation: String,
    pub maximum_rows: i64,
    pub timeout_seconds: i64,
    pub evidence_freshness_ceiling_seconds: i64,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct WaraObservationReceipt {
    pub recommendation_id: String,
    pub query_digest: String,
    pub evaluator_ref: String,
    pub evaluator_bindings_digest: String,
    pub workload_id: String,
    pub resource_ids: Vec<String>,
    pub inventory_generation: String,
    pub observed_at: String,
    pub recorded_at: String,
    pub evidence_digest: String,
    pub complete: bool,
    pub truncated: bool,
    pub conflicting: bool,
    pub synthetic: bool,
    pub satisfied: Option<bool>,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct WaraObservationError {
    pub message: String,
}

impl WaraObservationError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for WaraObservationError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for WaraObservationError {}

pub trait WaraAssessmentObservationProvider {
    fn observe(&self, plan: WaraReadPlan) -> WaraObservationReceipt;
}

pub const PUBLIC_EXPORTS: &[&str] = &["WaraAssessmentObservationProvider", "WaraObservationError", "WaraObservationReceipt", "WaraReadPlan"];
