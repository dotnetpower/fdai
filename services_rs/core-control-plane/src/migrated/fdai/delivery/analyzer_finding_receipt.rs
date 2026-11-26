#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum AnalyzerPublicationStatus {
    #[default]
    Published,
    PublishedReceiptUnrecorded,
    DuplicateSuppressed,
    ReconciledDuplicate,
    Uncertain,
    AwaitingReconciliation,
    Failed,
}

impl AnalyzerPublicationStatus {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Published => "published",
            Self::PublishedReceiptUnrecorded => "published_receipt_unrecorded",
            Self::DuplicateSuppressed => "duplicate_suppressed",
            Self::ReconciledDuplicate => "reconciled_duplicate",
            Self::Uncertain => "publish_uncertain",
            Self::AwaitingReconciliation => "awaiting_reconciliation",
            Self::Failed => "failed",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum AnalyzerEvidenceState {
    #[default]
    Complete,
    Incomplete,
    Conflicting,
    Missed,
}

impl AnalyzerEvidenceState {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Complete => "complete",
            Self::Incomplete => "incomplete",
            Self::Conflicting => "conflicting",
            Self::Missed => "missed",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct AnalyzerFindingReceipt {
    pub idempotency_key: String,
    pub signal: String,
    pub detection_latency_seconds: f64,
    pub evidence_complete: bool,
    pub publication: AnalyzerPublicationStatus,
    pub recovery_closed: Option<bool>,
    pub evidence_refs: Vec<String>,
    pub resource_ref: String,
    pub resource_kind: String,
    pub occurred_at: String,
    pub assessed_by: Option<String>,
    pub recovery_status: Option<String>,
    pub evidence_gaps: Vec<String>,
    pub recorded_at: Option<String>,
    pub current_state: String,
    pub evidence_state: Option<AnalyzerEvidenceState>,
    pub cause_claim_supported: bool,
    pub execution_authority: bool,
    pub severity: Option<String>,
    pub observation: String,
    pub assessment_status: Option<String>,
    pub recovery_finding_ref: Option<String>,
    pub recovery_prior_revision: Option<i64>,
}

impl AnalyzerFindingReceipt {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.idempotency_key.trim().is_empty() { return Err("idempotency_key must be non-empty"); }
        if self.signal.trim().is_empty() { return Err("signal must be non-empty"); }
        if self.resource_ref.trim().is_empty() { return Err("resource_ref must be non-empty"); }
        if self.resource_kind.trim().is_empty() { return Err("resource_kind must be non-empty"); }
        if self.occurred_at.trim().is_empty() { return Err("occurred_at must be non-empty"); }
        if self.current_state.trim().is_empty() { return Err("current_state must be non-empty"); }
        if self.observation.trim().is_empty() { return Err("observation must be non-empty"); }
        Ok(())
    }
}

impl AnalyzerFindingReceipt {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn to_dict(&self) -> std::collections::BTreeMap<String, String> {
        std::collections::BTreeMap::from([(String::from("schema_version"), String::from("1.0.0")), (String::from("idempotency_key"), self.idempotency_key.clone()), (String::from("resource_ref"), self.resource_ref.clone()), (String::from("resource_kind"), self.resource_kind.clone()), (String::from("signal"), self.signal.clone()), (String::from("occurred_at"), String::new()), (String::from("recorded_at"), String::new()), (String::from("current_state"), self.current_state.clone()), (String::from("detection_latency_seconds"), String::new()), (String::from("evidence_complete"), String::new()), (String::from("evidence_state"), String::new()), (String::from("publication"), String::new()), (String::from("recovery_closed"), String::new()), (String::from("recovery_status"), (self.recovery_status.clone()).unwrap_or_default()), (String::from("evidence_refs"), String::new()), (String::from("assessed_by"), (self.assessed_by.clone()).unwrap_or_default()), (String::from("evidence_gaps"), String::new()), (String::from("cause_claim_supported"), String::new()), (String::from("execution_authority"), String::new())])
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["AnalyzerEvidenceState", "AnalyzerFindingReceipt", "AnalyzerPublicationStatus"];
