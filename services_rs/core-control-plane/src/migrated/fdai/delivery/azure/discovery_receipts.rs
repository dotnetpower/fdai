pub const PREVIEW_FIELDS: &[&str] = &["name", "type", "resource_group", "location", "status"];
#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn build_provider_execution_receipt(mut plan: String, mut operation: String, mut page_count: i64, mut count: i64, mut preview_rows: Vec<std::collections::BTreeMap<String, String>>) -> Result<String, &'static str> {
    if ((page_count) < (1_i64)) || ((count) < (0_i64)) {
        return Err("execution receipt page_count MUST be  1 and count MUST be  0");
    }
    let values: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("backend"), String::from("azure_resource_graph\" if plan.backend is DiscoveryBackend.RESOURCE_GRAPH else \"azure_resource_manager")), (String::from("page_count"), String::new()), (String::from("commands"), String::new()), (String::from("plan_digest"), String::new())]);
    Ok(String::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn build_provider_coverage_canary_receipt(mut plan: String, mut operation: String, mut discovered_count: i64) -> Result<String, &'static str> {
    if (discovered_count) < (0_i64) {
        return Err("coverage canary discovered_count MUST be  0");
    }
    let values: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("backend"), String::from("azure_resource_graph")), (String::from("page_count"), String::new()), (String::from("commands"), String::new()), (String::from("plan_digest"), String::new())]);
    Ok(String::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn provider_execution_projection(mut receipt: String) -> std::collections::BTreeMap<String, String> {
    std::collections::BTreeMap::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn preview(mut row: std::collections::BTreeMap<String, String>) -> String {
    let projected: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::<String, String>::new();
    for (key, value) in row.clone() {
        let target_key: String = if (key.clone()) == (String::from("resourceGroup")) { String::from("resource_group") } else { key.clone() };
    }
    String::new()
}

pub const PUBLIC_EXPORTS: &[&str] = &["build_provider_coverage_canary_receipt", "build_provider_execution_receipt", "provider_execution_projection"];
