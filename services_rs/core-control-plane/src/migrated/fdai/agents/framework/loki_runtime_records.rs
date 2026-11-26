#[derive(Clone, Debug, Default, PartialEq)]
pub struct ChaosProposal {
    pub experiment_id: String,
    pub action_type: String,
    pub targets: Vec<String>,
    pub accepted: bool,
    pub reason: String,
    pub requested_target_count: i64,
    pub targets_truncated: bool,
    pub causal_hypothesis_ref: String,
    pub impact_envelope_id: String,
    pub recovery_plan_id: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Reservation {
    pub action_type: String,
    pub targets: Vec<String>,
    pub reserved_at: String,
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn parse_time(mut value: String) -> Result<String, &'static str> {
    if value.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

