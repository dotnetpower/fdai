#[derive(Clone, Debug, Default, PartialEq)]
pub struct ChangeObjectiveTrace {
    pub objective_id: String,
    pub utility: f64,
    pub confidence: f64,
    pub metric: String,
    pub expected_min: f64,
    pub expected_max: f64,
    pub observation_window_seconds: i64,
}

impl ChangeObjectiveTrace {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.objective_id.trim().is_empty() { return Err("objective_id must be non-empty"); }
        if self.metric.trim().is_empty() { return Err("metric must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ChangeDecisionTrace {
    pub context_snapshot_id: String,
    pub selected_option_id: String,
    pub option_scores: Vec<String>,
    pub margin: f64,
    pub requires_human_approval: bool,
    pub reason: String,
    pub protected_objective_ids: Vec<String>,
    pub active_constraint_ids: Vec<String>,
    pub selected_effects: Vec<ChangeObjectiveTrace>,
    pub violated_constraint_ids: Vec<String>,
    pub proposing_agents: Vec<String>,
    pub logic_receipt_refs: Vec<String>,
    pub simulation_receipt_refs: Vec<String>,
    pub constraint_evaluation_refs: Vec<String>,
    pub assumptions: Vec<String>,
    pub process_id: Option<String>,
    pub logic_release_digest: Option<String>,
}

impl ChangeDecisionTrace {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.context_snapshot_id.trim().is_empty() { return Err("context_snapshot_id must be non-empty"); }
        if self.selected_option_id.trim().is_empty() { return Err("selected_option_id must be non-empty"); }
        if self.reason.trim().is_empty() { return Err("reason must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ChangeResilienceTrace {
    pub execution_mode: String,
    pub blast_radius_scope: String,
    pub blast_radius_count: Option<i64>,
    pub rollback_kind: String,
    pub verification_status: String,
    pub execution_outcome: String,
    pub predicted_at: Option<String>,
    pub observation_deadline: Option<String>,
    pub observed_at: Option<String>,
    pub rollback_succeeded: Option<bool>,
}

impl ChangeResilienceTrace {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.execution_mode.trim().is_empty() { return Err("execution_mode must be non-empty"); }
        if self.blast_radius_scope.trim().is_empty() { return Err("blast_radius_scope must be non-empty"); }
        if self.rollback_kind.trim().is_empty() { return Err("rollback_kind must be non-empty"); }
        if self.verification_status.trim().is_empty() { return Err("verification_status must be non-empty"); }
        if self.execution_outcome.trim().is_empty() { return Err("execution_outcome must be non-empty"); }
        Ok(())
    }
}

impl ChangeObjectiveTrace {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn to_mapping(&self) -> std::collections::BTreeMap<String, String> {
        std::collections::BTreeMap::from([(String::from("objective_id"), self.objective_id.clone()), (String::from("utility"), String::new()), (String::from("confidence"), String::new()), (String::from("metric"), self.metric.clone()), (String::from("expected_min"), String::new()), (String::from("expected_max"), String::new()), (String::from("observation_window_seconds"), String::new())])
    }
}

impl ChangeDecisionTrace {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn to_mapping(&self) -> std::collections::BTreeMap<String, String> {
        std::collections::BTreeMap::from([(String::from("context_snapshot_id"), self.context_snapshot_id.clone()), (String::from("selected_option_id"), self.selected_option_id.clone()), (String::from("option_scores"), String::new()), (String::from("margin"), String::new()), (String::from("requires_human_approval"), String::new()), (String::from("reason"), self.reason.clone()), (String::from("protected_objective_ids"), String::new()), (String::from("active_constraint_ids"), String::new()), (String::from("selected_effects"), String::new()), (String::from("violated_constraint_ids"), String::new()), (String::from("proposing_agents"), String::new()), (String::from("logic_receipt_refs"), String::new()), (String::from("simulation_receipt_refs"), String::new()), (String::from("constraint_evaluation_refs"), String::new()), (String::from("assumptions"), String::new()), (String::from("process_id"), (self.process_id.clone()).unwrap_or_default()), (String::from("logic_release_digest"), (self.logic_release_digest.clone()).unwrap_or_default())])
    }
}

impl ChangeResilienceTrace {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn to_mapping(&self) -> std::collections::BTreeMap<String, String> {
        std::collections::BTreeMap::from([(String::from("execution_mode"), self.execution_mode.clone()), (String::from("blast_radius_scope"), self.blast_radius_scope.clone()), (String::from("blast_radius_count"), String::new()), (String::from("rollback_kind"), self.rollback_kind.clone()), (String::from("verification_status"), self.verification_status.clone()), (String::from("execution_outcome"), self.execution_outcome.clone()), (String::from("predicted_at"), String::new()), (String::from("observation_deadline"), String::new()), (String::from("observed_at"), String::new()), (String::from("rollback_succeeded"), String::new())])
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["ChangeDecisionTrace", "ChangeObjectiveTrace", "ChangeResilienceTrace"];
