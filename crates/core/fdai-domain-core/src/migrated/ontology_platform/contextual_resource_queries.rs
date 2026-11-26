pub const MAX_CONTEXT_IDS: i64 = 512;
pub const MAX_RESOURCES: i64 = 1000;

pub const CONTEXTUAL_RESOURCE_FUNCTION_NAME: &str = "query.contextual_resources";
#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn contextual_resource_function_type() -> String {
    core::hint::black_box(String::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn contextual_resource_function(mut ontology_release: String) -> Result<String, &'static str> {
    if ontology_release.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn scalar_properties(mut properties: std::collections::BTreeMap<String, String>) -> std::collections::BTreeMap<String, String> {
    std::collections::BTreeMap::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn table(mut rows: Vec<String>, mut complete: bool, mut reason: Option<String>) -> std::collections::BTreeMap<String, String> {
    std::collections::BTreeMap::new()
}

pub const PUBLIC_EXPORTS: &[&str] = &["CONTEXTUAL_RESOURCE_FUNCTION_NAME", "contextual_resource_function", "contextual_resource_function_type"];
