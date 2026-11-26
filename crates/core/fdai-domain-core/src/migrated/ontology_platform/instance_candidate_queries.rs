pub const INSTANCE_CANDIDATES_FUNCTION_NAME: &str = "query.ontology_instance_candidates";
#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn instance_candidates_function_type(mut object_type_names: Vec<String>) -> Result<String, &'static str> {
    let digest_schema: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("type"), String::from("string")), (String::from("pattern"), String::from("^sha256:[a-f0-9]{64}$"))]);
    Ok(String::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn instance_candidates_function(mut query: String, mut ontology_release_digest: String) -> Result<String, &'static str> {
    if query.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

