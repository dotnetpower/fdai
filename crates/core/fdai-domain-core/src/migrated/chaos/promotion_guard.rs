#[derive(Clone, Debug, Default, PartialEq)]
pub struct ChaosPromotionObservation {
    pub observed_at: String,
    pub audit_ref: String,
    pub runner_version: String,
    pub containment_compliant: bool,
    pub recovery_within_objective: bool,
    pub telemetry_complete: bool,
    pub stop_observed: bool,
    pub rollback_succeeded: bool,
    pub policy_escapes: i64,
}

impl ChaosPromotionObservation {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.observed_at.trim().is_empty() { return Err("observed_at must be non-empty"); }
        if self.audit_ref.trim().is_empty() { return Err("audit_ref must be non-empty"); }
        if self.runner_version.trim().is_empty() { return Err("runner_version must be non-empty"); }
        Ok(())
    }
}

impl ChaosPromotionObservation {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn regression_reasons(&self) -> Vec<String> {
        let mut reasons: Vec<String> = Vec::<String>::new();
        if !(self.containment_compliant) {
            reasons.push(String::from("impact_outside_envelope"));
        }
        if !(self.recovery_within_objective) {
            reasons.push(String::from("recovery_objective_missed"));
        }
        if !(self.telemetry_complete) {
            reasons.push(String::from("telemetry_incomplete"));
        }
        if !(self.stop_observed) {
            reasons.push(String::from("stop_condition_missed"));
        }
        if !(self.rollback_succeeded) {
            reasons.push(String::from("rollback_failed"));
        }
        if (self.policy_escapes) > (0_i64) {
            reasons.push(String::from("policy_escape"));
        }
        reasons.clone()
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ChaosPromotionGuard {
    pub initialized: bool,
}

impl ChaosPromotionGuard {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub fn observe(&self, mut key: String, mut action_type_names: Vec<String>, mut observation: ChaosPromotionObservation) -> Result<Vec<String>, &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["ChaosPromotionGuard", "ChaosPromotionObservation"];
