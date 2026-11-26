#[derive(Clone, Debug, Default, PartialEq)]
pub struct PlanningProgram {
    pub function_ref: String,
    pub reviewed_source: String,
    pub source_digest: String,
    pub sandbox_profile_id: String,
    pub allowed_read_tools: Vec<String>,
    pub limits: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct DecodedOutput {
    pub effects: Vec<String>,
    pub requires_review: bool,
    pub reason_code: String,
}

pub const REASON_CODE: &str = "^[a-z][a-z0-9_]{0,63}$";
pub trait ProgrammaticPlanningRunner {
    fn run(&self, request: String) -> String;
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ProgrammaticPlanningSimulator {
    pub initialized: bool,
}

impl ProgrammaticPlanningSimulator {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn simulate(&self, mut context: String, mut candidate_id: String, mut action_type: Option<String>, mut effects: Vec<String>, mut observed_at: String) -> String {
        let input_payload: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("candidate_id"), candidate_id.clone()), (String::from("action_type"), (action_type.clone()).unwrap_or_default()), (String::from("context_snapshot_id"), String::new()), (String::from("observed_at"), String::new()), (String::from("effects"), String::new())]);
        let mut status: String = simulation_status(String::new());
        String::new()
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn decode_output(mut raw: Option<String>) -> Result<String, &'static str> {
    let Some(mut raw) = raw.clone() else { return Err("simulation output is missing"); };
    Ok(String::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn decode_effect(mut value: String) -> Result<String, &'static str> {
    if value.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn effect_mapping(mut effect: String) -> std::collections::BTreeMap<String, String> {
    std::collections::BTreeMap::from([(String::from("objective_id"), String::new()), (String::from("utility"), String::new()), (String::from("confidence"), String::new()), (String::from("metric"), String::new()), (String::from("expected_min"), String::new()), (String::from("expected_max"), String::new()), (String::from("observation_window_seconds"), String::new())])
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn simulation_status(mut status: String) -> String {
    if status.is_empty() {
        return String::new();
    }
    String::new()
}

pub const PUBLIC_EXPORTS: &[&str] = &["PlanningProgram", "ProgrammaticPlanningRunner", "ProgrammaticPlanningSimulator"];
