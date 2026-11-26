#[derive(Clone, Debug, Default, PartialEq)]
pub struct AlertWorkflowBindings {
    pub workflows: Option<String>,
    pub binder: Option<String>,
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn registered_alert_actions(mut release: String) -> std::collections::BTreeMap<String, String> {
    std::collections::BTreeMap::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
#[allow(clippy::too_many_arguments)]
pub fn build_alert_workflow_bindings(mut workflow_coordinator: Option<String>, mut workflows: Vec<String>, mut action_types_by_name: std::collections::BTreeMap<String, String>, mut ontology_release: String, mut process_store: String, mut audit_store: String, mut promotion_registry: String, mut decision_evidence_provider: Option<String>, mut environment: Option<std::collections::BTreeMap<String, String>>, mut clock: String) -> Result<AlertWorkflowBindings, &'static str> {
    let Some(mut workflow_coordinator) = workflow_coordinator.clone() else { return Err("alert workflows require the canonical Workflow coordinator"); };
    let registered: std::collections::BTreeMap<String, String> = registered_alert_actions(ontology_release.clone());
    Ok(AlertWorkflowBindings::default())
}

pub const PUBLIC_EXPORTS: &[&str] = &["AlertWorkflowBindings", "build_alert_workflow_bindings", "registered_alert_actions"];
