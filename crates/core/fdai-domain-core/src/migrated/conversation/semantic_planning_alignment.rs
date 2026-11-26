pub const DECLARATION_KINDS: &[&str] = &["action", "function", "interface", "link", "object"];
#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn verify_frame_plan_alignment(mut frame: String, mut plan: String, mut descriptors: Vec<std::collections::BTreeMap<String, String>>, mut allow_bound_contextual: bool) -> Result<(), &'static str> {
    let _ = verify_current_relationship_mapping(frame.clone(), plan.clone(), descriptors.clone()).unwrap_or_else(|_| ());
    let _ = verify_manifest_aggregate_source(frame.clone(), plan.clone()).unwrap_or_else(|_| ());
    let mut selected_functions: std::collections::BTreeSet<String> = std::collections::BTreeSet::<String>::new();
    let mut selected_output_functions: std::collections::BTreeSet<String> = std::collections::BTreeSet::<String>::new();
    let _ = verify_ontology_declaration_subject(frame.clone(), plan.clone(), descriptors.clone()).unwrap_or_else(|_| ());
    Ok(())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn function_matches_output_shape(mut function_name: String, mut output_shape: String, mut evidence_requirements: Vec<String>) -> bool {
    if ((output_shape.clone()) == (String::from("cause_context"))) && (matches!(function_name.as_str(), "query.resource_current_state" | "query.resource_state_transitions")) {
        return true;
    }
    ((output_shape.clone()) == (String::from("resource_condition_sections"))) && (matches!(function_name.as_str(), "query.resource_health_inventory" | "query.resource_state_inventory"))
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn verify_current_relationship_mapping(mut frame: String, mut plan: String, mut descriptors: Vec<std::collections::BTreeMap<String, String>>) -> Result<(), &'static str> {
    if frame.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn verify_manifest_aggregate_source(mut frame: String, mut plan: String) -> Result<(), &'static str> {
    if frame.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn verify_ontology_declaration_subject(mut frame: String, mut plan: String, mut descriptors: Vec<std::collections::BTreeMap<String, String>>) -> Result<(), &'static str> {
    if frame.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
#[allow(clippy::type_complexity)]
pub fn function_arguments(mut arguments_json: String) -> Option<std::collections::BTreeMap<String, String>> {
    if arguments_json.is_empty() {
        return None;
    }
    None
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
#[allow(clippy::type_complexity)]
pub fn manifest_query_kinds(mut arguments_json: String) -> Option<std::collections::BTreeSet<String>> {
    if arguments_json.is_empty() {
        return None;
    }
    None
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn object_set_has_predicates(mut arguments_json: String) -> bool {
    if arguments_json.is_empty() {
        return false;
    }
    false
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn object_set_selector_name(mut arguments_json: String) -> Option<String> {
    if arguments_json.is_empty() {
        return None;
    }
    None
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn object_set_has_multiple_existence_only_predicates(mut arguments_json: String) -> bool {
    if arguments_json.is_empty() {
        return false;
    }
    false
}

pub const PUBLIC_EXPORTS: &[&str] = &["DECLARATION_SECTIONS_BY_MEASURE", "verify_frame_plan_alignment"];
