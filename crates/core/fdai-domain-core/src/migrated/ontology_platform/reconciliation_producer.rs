#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ReconciliationRequestProductionStatus {
    #[default]
    Published,
    NotApplicable,
    Held,
}

impl ReconciliationRequestProductionStatus {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Published => "published",
            Self::NotApplicable => "not_applicable",
            Self::Held => "held",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ExecutedActionObservation {
    pub evidence: String,
    pub observation_context: String,
    pub deadline: String,
    pub evaluated_at: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ReconciliationRequestProduction {
    pub status: ReconciliationRequestProductionStatus,
    pub reason_code: String,
    pub reconciliation_id: Option<String>,
}

pub trait ExecutedActionReconciliationArtifactSource {
    fn resolve(&self, action: String) -> String;
}

pub trait ExecutedActionObservationSource {
    fn observe(&self, action: String, artifacts: String, execution_outcome: String, execution_receipt_ref: Option<String>, correlation_id: String) -> String;
}

pub trait ExecutedActionObservationCollector {
    fn collect(&self, action: String, artifacts: String, execution_outcome: String, execution_completed_at: String, execution_receipt_ref: Option<String>, correlation_id: String) -> String;
}

pub trait EffectReconciliationRequestSink {
    fn call(&self, action: String, execution_outcome: String, execution_receipt_ref: Option<String>, correlation_id: Option<String>) -> String;
}

pub const PUBLIC_EXPORTS: &[&str] = &["EffectReconciliationRequestSink", "ExecutedActionObservation", "ExecutedActionObservationCollector", "ExecutedActionObservationSource", "ExecutedActionReconciliationArtifactSource", "ReconciliationRequestProduction", "ReconciliationRequestProductionStatus"];
