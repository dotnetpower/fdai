#[derive(Clone, Debug, Default, PartialEq)]
pub struct WorkflowSpec {
    pub id: String,
    pub name: String,
    pub primary_agent: String,
    pub participating_agents: Vec<String>,
    pub trigger: String,
    pub default_mode: String,
    pub promotion_gate: String,
    pub trace_ref: String,
    pub trace_assertions: Vec<String>,
    pub planned_agents: Vec<String>,
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn workflow(mut id: String) -> WorkflowSpec {
    if id.is_empty() {
        return Default::default();
    }
    Default::default()
}

pub const PUBLIC_EXPORTS: &[&str] = &["WORKFLOWS", "WORKFLOWS_BY_ID", "WorkflowSpec", "workflow"];
