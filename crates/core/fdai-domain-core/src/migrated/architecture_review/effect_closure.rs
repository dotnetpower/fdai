#[derive(Clone, Debug, Default, PartialEq)]
pub struct ArchitectureReviewExpectedEffect {
    pub effect_id: String,
    pub metric: String,
    pub target_ref: String,
    pub expected_min: f64,
    pub expected_max: f64,
    pub window_seconds: i64,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ArchitectureReviewActionRunLink {
    pub review_case_id: String,
    pub change_id: String,
    pub decision_case_id: String,
    pub impact_envelope_id: String,
    pub action_run_id: String,
    pub selected_option_id: String,
    pub action_type: String,
    pub executor_principal: String,
    pub idempotency_key: String,
    pub target_lock_ref: String,
    pub stop_condition_ref: String,
    pub rollback_ref: String,
    pub executed_at: String,
    pub expected_effects: Vec<ArchitectureReviewExpectedEffect>,
    pub mode: String,
    pub arb_execution_authority: bool,
}

impl ArchitectureReviewActionRunLink {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.mode.as_str(), "shadow" | "enforce") { return Err("invalid mode literal"); }
        if self.arb_execution_authority { return Err("arb_execution_authority violated literal bool invariant"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ArchitectureReviewEffectObservation {
    pub observation_id: String,
    pub effect_id: String,
    pub action_run_id: String,
    pub observer_principal: String,
    pub observed_value: Option<f64>,
    pub observed_at: String,
    pub evidence_digest: String,
    pub complete: bool,
    pub stop_condition_triggered: bool,
    pub protected_objective_violated: bool,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ArchitectureReviewRecoveryRequest {
    pub recovery_id: String,
    pub review_case_id: String,
    pub change_id: String,
    pub action_run_id: String,
    pub impact_envelope_id: String,
    pub rollback_ref: String,
    pub stop_condition_ref: String,
    pub failed_effect_ids: Vec<String>,
    pub reason_codes: Vec<String>,
    pub requested_at: String,
    pub target_agent: String,
    pub arb_execution_authority: bool,
}

impl ArchitectureReviewRecoveryRequest {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.target_agent.as_str(), "Vidar") { return Err("invalid target_agent literal"); }
        if self.arb_execution_authority { return Err("arb_execution_authority violated literal bool invariant"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ArchitectureReviewEffectClosureResult {
    pub review_case_id: String,
    pub change_id: String,
    pub decision_case_id: String,
    pub impact_envelope_id: String,
    pub action_run_id: String,
    pub status: String,
    pub review_status: String,
    pub closed_effect_ids: Vec<String>,
    pub pending_effect_ids: Vec<String>,
    pub failed_effect_ids: Vec<String>,
    pub reason_codes: Vec<String>,
    #[allow(clippy::type_complexity)]
    pub recovery_request: Option<Box<ArchitectureReviewRecoveryRequest>>,
    pub closure_digest: String,
    pub arb_execution_authority: bool,
}

impl ArchitectureReviewEffectClosureResult {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.status.as_str(), "closed_conformant" | "pending_observation" | "recovery_required") { return Err("invalid status literal"); }
        if !matches!(self.review_status.as_str(), "conformant" | "pending" | "reopened") { return Err("invalid review_status literal"); }
        if self.arb_execution_authority { return Err("arb_execution_authority violated literal bool invariant"); }
        Ok(())
    }
}

pub const HEX_DIGITS: &[&str] = &["0123456789abcdef"];
impl ArchitectureReviewRecoveryRequest {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn to_mapping(&self) -> std::collections::BTreeMap<String, String> {
        std::collections::BTreeMap::from([(String::from("recovery_id"), self.recovery_id.clone()), (String::from("review_case_id"), self.review_case_id.clone()), (String::from("change_id"), self.change_id.clone()), (String::from("action_run_id"), self.action_run_id.clone()), (String::from("impact_envelope_id"), self.impact_envelope_id.clone()), (String::from("target_agent"), self.target_agent.clone()), (String::from("rollback_ref"), self.rollback_ref.clone()), (String::from("stop_condition_ref"), self.stop_condition_ref.clone()), (String::from("failed_effect_ids"), String::new()), (String::from("reason_codes"), String::new()), (String::from("requested_at"), String::new()), (String::from("arb_execution_authority"), String::new())])
    }
}

impl ArchitectureReviewEffectClosureResult {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn to_mapping(&self) -> std::collections::BTreeMap<String, String> {
        std::collections::BTreeMap::from([(String::from("review_case_id"), self.review_case_id.clone()), (String::from("change_id"), self.change_id.clone()), (String::from("decision_case_id"), self.decision_case_id.clone()), (String::from("impact_envelope_id"), self.impact_envelope_id.clone()), (String::from("action_run_id"), self.action_run_id.clone()), (String::from("status"), self.status.clone()), (String::from("review_status"), self.review_status.clone()), (String::from("closed_effect_ids"), String::new()), (String::from("pending_effect_ids"), String::new()), (String::from("failed_effect_ids"), String::new()), (String::from("reason_codes"), String::new()), (String::from("recovery_request"), String::new()), (String::from("closure_digest"), self.closure_digest.clone()), (String::from("arb_execution_authority"), String::new())])
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn require_non_empty(mut name: String, mut value: String) -> Result<String, &'static str> {
    let stripped: String = (value.clone()).trim().to_string();
    if (stripped.clone()).is_empty() {
        return Err("architecture review effect closure name MUST be non-empty");
    }
    Ok(stripped.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn require_sha256(mut name: String, mut value: String) -> Result<String, &'static str> {
    Ok(value.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn require_aware_datetime(mut name: String, mut value: String) -> Result<String, &'static str> {
    Ok(value.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn digest(mut value: String) -> String {
    if value.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn evaluate_architecture_review_effect_closure(mut link: ArchitectureReviewActionRunLink, mut observations: Vec<ArchitectureReviewEffectObservation>, mut allowed_observer_principals: std::collections::BTreeSet<String>) -> Result<ArchitectureReviewEffectClosureResult, &'static str> {
    if (allowed_observer_principals.clone()).is_empty() {
        return Err("allowed_observer_principals MUST NOT be empty");
    }
    if (allowed_observer_principals.clone()).contains((link.executor_principal.clone()).as_str()) {
        return Err("executor_principal MUST NOT be an allowed independent observer");
    }
    let accepted_by_effect: std::collections::BTreeMap<String, Vec<ArchitectureReviewEffectObservation>> = std::collections::BTreeMap::<String, Vec<ArchitectureReviewEffectObservation>>::new();
    let mut reasons: std::collections::BTreeSet<String> = std::collections::BTreeSet::<String>::new();
    for obs in observations.clone() {
        if (obs.action_run_id.clone()) != (link.action_run_id.clone()) {
            reasons.insert(format!("action_run_mismatch:{}", obs.observation_id.clone()));
            continue;
        }
        if ((obs.observer_principal.clone()) == (link.executor_principal.clone())) || (!((allowed_observer_principals.clone()).contains((obs.observer_principal.clone()).as_str()))) {
            reasons.insert(format!("self_scored_or_unauthorized_observer:{}", obs.observer_principal.clone()));
            continue;
        }
    }
    let mut closed: Vec<String> = Vec::<String>::new();
    let mut pending: Vec<String> = Vec::<String>::new();
    let mut failed: Vec<String> = Vec::<String>::new();
    let mut latest_failure_time: Option<String> = None;
    for effect in link.expected_effects.clone() {
        let mut effect_failed: bool = false;
        let mut effect_complete: bool = true;
        if effect_failed {
            failed.push(effect.effect_id.clone());
        } else if !(effect_complete) {
            pending.push(effect.effect_id.clone());
        } else {
            closed.push(effect.effect_id.clone());
        }
    }
    let sorted_reasons: Vec<String> = (reasons.clone()).into_iter().collect::<Vec<String>>();
    let mut recovery_request: Option<ArchitectureReviewRecoveryRequest> = None;
    if !(failed.clone()).is_empty() {
        let mut status: String = String::from("recovery_required");
        let mut review_status: String = String::from("reopened");
        let Some(mut latest_failure_time) = latest_failure_time.clone() else { return Err("failed effect observation is missing timestamp"); };
        recovery_request = Some(ArchitectureReviewRecoveryRequest { recovery_id: format!("arb-recovery:{}", link.action_run_id.clone()), review_case_id: link.review_case_id.clone(), change_id: link.change_id.clone(), action_run_id: link.action_run_id.clone(), impact_envelope_id: link.impact_envelope_id.clone(), rollback_ref: link.rollback_ref.clone(), stop_condition_ref: link.stop_condition_ref.clone(), failed_effect_ids: failed.clone(), reason_codes: sorted_reasons.clone(), requested_at: latest_failure_time.clone(), ..Default::default() });
    } else if (!(pending.clone()).is_empty()) || (!(sorted_reasons.clone()).is_empty()) {
        let mut status: String = String::from("pending_observation");
        let mut review_status: String = String::from("pending");
    } else {
        let mut status: String = String::from("closed_conformant");
        let mut review_status: String = String::from("conformant");
    }
    let material: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("review_case_id"), link.review_case_id.clone()), (String::from("change_id"), link.change_id.clone()), (String::from("decision_case_id"), link.decision_case_id.clone()), (String::from("impact_envelope_id"), link.impact_envelope_id.clone()), (String::from("action_run_id"), link.action_run_id.clone()), (String::from("status"), String::new()), (String::from("review_status"), String::new()), (String::from("closed_effect_ids"), String::new()), (String::from("pending_effect_ids"), String::new()), (String::from("failed_effect_ids"), String::new()), (String::from("reason_codes"), String::new()), (String::from("recovery_request"), String::new()), (String::from("arb_execution_authority"), String::new())]);
    Ok(ArchitectureReviewEffectClosureResult { review_case_id: link.review_case_id.clone(), change_id: link.change_id.clone(), decision_case_id: link.decision_case_id.clone(), impact_envelope_id: link.impact_envelope_id.clone(), action_run_id: link.action_run_id.clone(), closed_effect_ids: closed.clone(), pending_effect_ids: pending.clone(), failed_effect_ids: failed.clone(), reason_codes: sorted_reasons.clone(), recovery_request: (recovery_request.clone()).map(Box::new), closure_digest: digest(String::new()), ..Default::default() })
}

pub const PUBLIC_EXPORTS: &[&str] = &["ArchitectureReviewActionRunLink", "ArchitectureReviewEffectClosureResult", "ArchitectureReviewEffectObservation", "ArchitectureReviewExpectedEffect", "ArchitectureReviewRecoveryRequest", "evaluate_architecture_review_effect_closure"];
