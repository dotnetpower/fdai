use std::collections::BTreeMap;
#[derive(Clone, Debug, Default, PartialEq)]
pub struct PromotionGate {
    pub min_shadow_days: i64,
    pub min_samples: i64,
    pub min_accuracy: f64,
    pub max_policy_escapes: i64,
    pub min_fidelity: Option<f64>,
    pub max_recurrence_rate: Option<f64>,
}

impl PromotionGate {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !(1_i64..=9223372036854775807_i64).contains(&self.min_shadow_days) { return Err("min_shadow_days out of bounds"); }
        if !(1_i64..=9223372036854775807_i64).contains(&self.min_samples) { return Err("min_samples out of bounds"); }
        if !(0_i64..=9223372036854775807_i64).contains(&self.max_policy_escapes) { return Err("max_policy_escapes out of bounds"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct WorkflowTrigger {
    pub kind: String,
    pub signal_type: Option<String>,
    pub signal_reference_kind: Option<String>,
    pub schedule: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct WorkflowStep {
    pub id: String,
    pub kind: String,
    pub action_type_ref: Option<String>,
    pub guard_rule_ref: Option<String>,
    pub gate_ref: Option<String>,
    pub compensated_by: Option<String>,
    pub on_failure: Option<String>,
    pub params: BTreeMap<String, String>,
    pub wait_for: Option<String>,
    pub timeout_seconds: Option<i64>,
    pub approval_role: Option<String>,
    pub quorum: i64,
    pub no_self_approval: bool,
    pub outcomes: Vec<String>,
    pub branches: Vec<String>,
}

impl WorkflowStep {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !(1_i64..=9223372036854775807_i64).contains(&self.quorum) { return Err("quorum out of bounds"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Workflow {
    pub schema_version: String,
    pub name: String,
    pub version: String,
    pub trigger: Box<WorkflowTrigger>,
    pub default_mode: String,
    pub promotion_gate: Box<PromotionGate>,
    pub steps: Vec<WorkflowStep>,
    pub description: Option<String>,
    pub anti_scope: Option<String>,
}

impl WorkflowTrigger {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn payload_matches_kind(&self) -> Result<WorkflowTrigger, &'static str> {
        Err("runtime_binding_required")
    }
}

impl WorkflowStep {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn kind_contract(&self) -> Result<WorkflowStep, &'static str> {
        if !(self.no_self_approval) {
            return Err("no_self_approval MUST stay enabled catalog data cannot authorize self-ap");
        }
        Ok(self.clone())
    }
}

impl Workflow {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn structural_invariants(&self) -> Result<Workflow, &'static str> {
        let mut seen: std::collections::BTreeSet<String> = std::collections::BTreeSet::<String>::new();
        for step in self.steps.clone() {
            if (seen.clone()).contains((step.id.clone()).as_str()) {
                return Err("duplicate step id step.idr");
            }
            seen.insert(step.id.clone());
        }
        Ok(self.clone())
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["PromotionGate", "Workflow", "WorkflowStep", "WorkflowTrigger"];
