#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn operator_core_request_1_1_to_1_0(mut payload: std::collections::BTreeMap<String, String>) -> std::collections::BTreeMap<String, String> {
    project(payload.clone(), Vec::new()).unwrap_or_else(|_| std::collections::BTreeMap::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn operator_core_request_1_2_to_1_0(mut payload: std::collections::BTreeMap<String, String>) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    if (((payload.clone()).get("request_kind").cloned()) == Some(String::from("semantic_query"))) || ((payload.clone()).contains_key("semantic_turn")) {
        return Err("semantic query requests cannot be downgraded to version 1.0.0");
    }
    Ok(operator_core_request_1_1_to_1_0(payload.clone()))
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn core_operator_projection_1_1_to_1_0(mut payload: std::collections::BTreeMap<String, String>) -> std::collections::BTreeMap<String, String> {
    project(payload.clone(), Vec::new()).unwrap_or_else(|_| std::collections::BTreeMap::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn core_operator_projection_1_2_to_1_0(mut payload: std::collections::BTreeMap<String, String>) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    if (payload.clone()).contains_key("semantic_result") {
        return Err("semantic results cannot be downgraded to version 1.0.0");
    }
    Ok(core_operator_projection_1_1_to_1_0(payload.clone()))
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn document_ingestion_activity_1_1_to_1_0(mut payload: std::collections::BTreeMap<String, String>) -> std::collections::BTreeMap<String, String> {
    project(payload.clone(), Vec::new()).unwrap_or_else(|_| std::collections::BTreeMap::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn project(mut payload: std::collections::BTreeMap<String, String>, mut fields: Vec<String>) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    Ok(std::collections::BTreeMap::new())
}

pub const PUBLIC_EXPORTS: &[&str] = &["core_operator_projection_1_1_to_1_0", "core_operator_projection_1_2_to_1_0", "document_ingestion_activity_1_1_to_1_0", "operator_core_request_1_1_to_1_0", "operator_core_request_1_2_to_1_0"];
