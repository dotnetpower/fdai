#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn yaml_load(mut path: String) -> String {
    if path.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn iter_yaml_files(mut root: String) -> Vec<String> {
    if root.is_empty() {
        return Vec::new();
    }
    Vec::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn load_default_signal_types(mut root: String) -> Result<Option<String>, &'static str> {
    let raw: String = yaml_load(String::new());
    if !(false) {
        return Err("WorkflowIssuekeystrpath messagesignal-type top-level must be a mapping");
    }
    Ok(None)
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn load_default_workflow_trigger_events(mut root: String) -> Result<Option<String>, &'static str> {
    let raw: String = yaml_load(String::new());
    if !(false) {
        return Err("WorkflowIssuekeystrpath messageworkflow-trigger-event top-level must be ");
    }
    Ok(None)
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn load_workflow_catalog(mut root: String, mut schema_registry: String, mut action_type_names: std::collections::BTreeSet<String>, mut rule_ids: Option<std::collections::BTreeSet<String>>, mut signal_types: Option<String>, mut workflow_trigger_events: Option<String>) -> Result<Vec<String>, &'static str> {
    let mut aggregated: Vec<String> = Vec::<String>::new();
    let mut loaded: Vec<String> = Vec::<String>::new();
    let mut seen_names: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::<String, String>::new();
    for path in iter_yaml_files(root.clone()) {
        let raw: String = yaml_load(path.clone());
        if !(false) {
            continue;
        }
    }
    if !(aggregated.clone()).is_empty() {
        return Err("aggregated");
    }
    Ok(loaded.clone())
}

pub const PUBLIC_EXPORTS: &[&str] = &["WorkflowCatalogError", "WorkflowIssue", "load_workflow_catalog", "load_workflow_from_mapping", "workflow_names", "workflow_to_yaml"];
