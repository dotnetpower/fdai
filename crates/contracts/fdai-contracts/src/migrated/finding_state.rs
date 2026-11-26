#[derive(Clone, Debug, Default, PartialEq)]
pub struct FindingState {
    pub schema_version: String,
    pub finding_id: String,
    pub revision: i64,
    pub notification_version: i64,
    pub notification_reason: String,
    pub notification_changed_at: String,
    pub resource_ref: String,
    pub resource_kind: String,
    pub signal: String,
    pub severity: String,
    pub status: String,
    pub observation: String,
    pub observation_key: String,
    pub observation_digest: String,
    pub first_seen_at: String,
    pub occurred_at: String,
    pub recorded_at: String,
    pub current_state: String,
    pub evidence_complete: bool,
    pub evidence_state: String,
    pub recovery_closed: Option<bool>,
    pub assessed_by: Option<String>,
    pub evidence_refs: Vec<String>,
    pub evidence_gaps: Vec<String>,
    pub publication: String,
    pub cause_claim_supported: bool,
    pub execution_authority: bool,
}

impl FindingState {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.schema_version.as_str(), "1.0.0") { return Err("invalid schema_version literal"); }
        if !matches!(self.notification_reason.as_str(), "opened" | "escalated" | "recovered") { return Err("invalid notification_reason literal"); }
        if !matches!(self.severity.as_str(), "critical" | "high" | "medium" | "low") { return Err("invalid severity literal"); }
        if !matches!(self.status.as_str(), "active" | "resolved") { return Err("invalid status literal"); }
        if self.cause_claim_supported { return Err("cause_claim_supported violated literal bool invariant"); }
        if self.execution_authority { return Err("execution_authority violated literal bool invariant"); }
        Ok(())
    }
}

pub const FINDING_STATE_PREFIX: &str = "runtime:analyzer-finding-current:";
#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn is_operational_finding(mut signal: String, mut assessment_status: Option<String>) -> bool {
    if signal.is_empty() {
        return false;
    }
    false
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn finding_identity(mut resource_kind: String, mut resource_ref: String, mut signal: String) -> String {
    if resource_kind.is_empty() {
        return String::new();
    }
    String::new()
}

