#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
#[allow(clippy::type_complexity)]
#[allow(clippy::too_many_arguments)]
pub fn attach_metric_provider(mut container: String, mut identity: String, mut http_client: String, mut monitor_workspace_id: Option<String>, mut monitor_queries: Option<std::collections::BTreeMap<String, String>>, mut metrics_api_queries: Option<std::collections::BTreeMap<String, String>>, mut prometheus_base_url: Option<String>, mut prometheus_queries: Option<std::collections::BTreeMap<String, String>>, mut prometheus_audience: Option<String>) -> String {
    let mut routes: Vec<String> = Vec::<String>::new();
    let mut log_summary: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::<String, String>::new();
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
#[allow(clippy::type_complexity)]
pub fn build_prometheus_route(mut base_url: String, mut queries: Option<std::collections::BTreeMap<String, String>>, mut audience: Option<String>, mut identity: String, mut http_client: String) -> (String, std::collections::BTreeSet<String>, std::collections::BTreeMap<String, String>) {
    let detail: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("query_count"), String::new()), (String::from("query_source"), if queries.is_some() { String::from("override") } else { String::from("aks_managed_prometheus_queries") })]);
    (String::new(), std::collections::BTreeSet::new(), std::collections::BTreeMap::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
#[allow(clippy::type_complexity)]
pub fn build_metrics_api_route(mut queries: Option<std::collections::BTreeMap<String, String>>, mut identity: String, mut http_client: String) -> (String, std::collections::BTreeSet<String>, std::collections::BTreeMap<String, String>) {
    let detail: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("template_count"), String::new()), (String::from("template_source"), if queries.is_some() { String::from("override") } else { String::from("azure_metrics_api_queries") })]);
    (String::new(), std::collections::BTreeSet::new(), std::collections::BTreeMap::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
#[allow(clippy::type_complexity)]
pub fn build_aml_route(mut workspace_id: String, mut queries: Option<std::collections::BTreeMap<String, String>>, mut identity: String, mut http_client: String) -> (String, std::collections::BTreeSet<String>, std::collections::BTreeMap<String, String>) {
    let detail: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("workspace_id"), workspace_id.clone()), (String::from("query_count"), String::new()), (String::from("query_source"), if queries.is_some() { String::from("override") } else { String::from("default_metric_queries") })]);
    (String::new(), std::collections::BTreeSet::new(), std::collections::BTreeMap::new())
}

pub const PUBLIC_EXPORTS: &[&str] = &["attach_metric_provider"];
