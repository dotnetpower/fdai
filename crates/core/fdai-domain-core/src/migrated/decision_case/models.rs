#[derive(Clone, Debug, Default, PartialEq)]
pub struct ActionArgumentProposal {
    pub name: String,
    pub value_digest: String,
    pub redacted: bool,
    pub safe_value_json: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ActionArguments {
    pub arguments_json: String,
    pub arguments_digest: String,
    pub bindings: Vec<ActionArgumentProposal>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ObjectiveEffect {
    pub objective_id: String,
    pub utility: f64,
    pub confidence: f64,
    pub metric: String,
    pub expected_min: f64,
    pub expected_max: f64,
    pub observation_window_seconds: i64,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ActionOption {
    pub option_id: String,
    pub action_type: Option<String>,
    pub effects: Vec<ObjectiveEffect>,
    pub evidence_refs: Vec<String>,
    pub violated_constraint_ids: Vec<String>,
    pub proposing_agents: Vec<String>,
    pub logic_receipt_refs: Vec<String>,
    pub simulation_receipt_refs: Vec<String>,
    pub constraint_evaluation_refs: Vec<String>,
    pub assumptions: Vec<String>,
    #[allow(clippy::type_complexity)]
    pub arguments: Option<Box<ActionArguments>>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct DecisionCase {
    pub case_id: String,
    pub correlation_id: String,
    pub context_snapshot_id: String,
    pub created_at: String,
    pub no_action_effects: Vec<ObjectiveEffect>,
    pub options: Vec<ActionOption>,
    pub protected_objective_ids: Vec<String>,
    pub active_constraint_ids: Vec<String>,
    pub evidence_refs: Vec<String>,
    pub process_id: Option<String>,
    pub logic_release_digest: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct DecisionSelection {
    pub selected_option_id: Option<String>,
    pub objective_scores: Vec<String>,
    pub margin: f64,
    pub requires_human_approval: bool,
    pub reason: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct DecisionClosure {
    pub case_id: String,
    pub selected_option_id: String,
    pub outcome_id: String,
    pub effect_verified: bool,
    pub guard_regression: bool,
    pub reusable: bool,
    pub reason: String,
}

pub const ARGUMENT_NAME: &str = "^[a-z][a-z0-9_]{0,63}$";
impl ActionArguments {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn create(mut arguments: std::collections::BTreeMap<String, String>, mut redacted_names: std::collections::BTreeSet<String>) -> Result<ActionArguments, &'static str> {
        let values: std::collections::BTreeMap<String, String> = arguments.clone();
        let arguments_json: String = canonical_json(String::new()).unwrap_or_else(|_| String::new());
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub fn values(&self) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
        Ok(std::collections::BTreeMap::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn to_mapping(&self) -> std::collections::BTreeMap<String, String> {
        std::collections::BTreeMap::from([(String::from("digest"), self.arguments_digest.clone()), (String::from("projection"), String::new()), (String::from("bindings"), String::new())])
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn canonical_json(mut value: String) -> Result<String, &'static str> {
    if value.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn content_digest(mut value: String) -> String {
    if value.is_empty() {
        return String::new();
    }
    String::new()
}

