#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn discovered_telemetry_holds(mut monitor_workspace_id: Option<String>) -> std::collections::BTreeMap<String, String> {
    std::collections::BTreeMap::new()
}

pub const PUBLIC_EXPORTS: &[&str] = &["ANALYZER_METRICS_BY_RESOURCE_TYPE", "discovered_telemetry_holds"];
