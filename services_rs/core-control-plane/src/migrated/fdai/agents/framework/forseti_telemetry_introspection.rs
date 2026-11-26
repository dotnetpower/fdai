#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn telemetry_recipe_facts() -> std::collections::BTreeMap<String, String> {
    std::collections::BTreeMap::from([(String::from("telemetry_recipe_catalog_version"), String::new()), (String::from("telemetry_recipe_catalog_digest"), String::new()), (String::from("telemetry_recipe_ids"), String::new()), (String::from("raw_kql_available"), String::new()), (String::from("query_execution_authority"), String::new())])
}

pub const PUBLIC_EXPORTS: &[&str] = &["telemetry_recipe_facts"];
