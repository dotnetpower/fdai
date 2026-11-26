use std::collections::BTreeMap;
#[derive(Clone, Debug, Default, PartialEq)]
pub struct RollbackRef {
    pub kind: String,
    pub reference: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct BlastRadius {
    pub scope: String,
    pub count: Option<i64>,
    pub rate_per_minute: Option<i64>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct WorkflowActionRef {
    pub process_id: String,
    pub step_id: String,
    pub proposal_ref: String,
    pub attempt: i64,
}

impl WorkflowActionRef {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !(1_i64..=9223372036854775807_i64).contains(&self.attempt) { return Err("attempt out of bounds"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Action {
    pub schema_version: String,
    pub action_id: String,
    pub idempotency_key: String,
    pub event_id: String,
    pub action_type: String,
    pub target_resource_ref: String,
    pub operation: String,
    pub params: BTreeMap<String, String>,
    pub stop_condition: String,
    pub stop_conditions: Vec<String>,
    pub rollback_ref: Box<RollbackRef>,
    pub blast_radius: Box<BlastRadius>,
    pub mode: String,
    pub citing_rules: Vec<String>,
    pub created_at: String,
    pub action_type_ref: Option<String>,
    pub executor_identity_ref: Option<String>,
    #[allow(clippy::type_complexity)]
    pub workflow_action: Option<Box<WorkflowActionRef>>,
}

impl Action {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn stop_condition_shorthand_matches_contract(&self) -> Result<Action, &'static str> {
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn action_type_reference_matches_name(&self) -> Result<Action, &'static str> {
        Err("runtime_binding_required")
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["Action", "BlastRadius", "RollbackRef", "WorkflowActionRef"];
