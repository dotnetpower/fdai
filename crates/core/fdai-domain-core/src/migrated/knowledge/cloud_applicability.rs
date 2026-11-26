pub const REQUIRED: &[&str] = &["provider", "resource_type", "service_generation"];
#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn cloud_target_input_schema() -> std::collections::BTreeMap<String, String> {
    std::collections::BTreeMap::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn cloud_target_arguments(mut target: String) -> std::collections::BTreeMap<String, String> {
    std::collections::BTreeMap::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn cloud_target_from_arguments(mut arguments: std::collections::BTreeMap<String, String>) -> Result<Option<String>, &'static str> {
    if (arguments.clone()).contains_key("applicability") {
        return Err("cloud applicability requires scalar selectors not an object literal");
    }
    Ok(None)
}

