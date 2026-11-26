#[derive(Clone, Debug, Default, PartialEq)]
pub struct HandoverEvidenceObservation {
    pub evidence_ref: String,
    pub digest: String,
    pub kind: String,
    pub slot: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct HandoverGoalObservation {
    pub schema_version: String,
    pub goal_id: String,
    pub assignment_case_id: Option<String>,
    pub agent_name: String,
    pub scope_ref: String,
    pub prompt_ref: String,
    pub priority: i64,
    pub state: String,
    pub revision: i64,
    pub source_digest: Option<String>,
    pub evidence: Vec<HandoverEvidenceObservation>,
}

impl HandoverGoalObservation {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.schema_version.as_str(), "1.0.0" | "1.1.0") { return Err("invalid schema_version literal"); }
        if !(1_i64..=100_i64).contains(&self.priority) { return Err("priority out of bounds"); }
        if !matches!(self.state.as_str(), "not_started" | "in_progress" | "blocked" | "ready_for_review" | "accepted" | "stale" | "declined") { return Err("invalid state literal"); }
        if !(1_i64..=9223372036854775807_i64).contains(&self.revision) { return Err("revision out of bounds"); }
        Ok(())
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn handover_observation_fields(mut record: std::collections::BTreeMap<String, String>) -> std::collections::BTreeMap<String, String> {
    std::collections::BTreeMap::new()
}

pub const PUBLIC_EXPORTS: &[&str] = &["HandoverEvidenceObservation", "HandoverGoalObservation", "handover_observation_fields"];
