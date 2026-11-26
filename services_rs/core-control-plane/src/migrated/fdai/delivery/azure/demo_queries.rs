pub const METRIC_HOST_CPU_PERCENT: &str = "host.cpu.percent";
pub const METRIC_HOST_MEMORY_AVAILABLE_PCT: &str = "host.memory.available_pct";
pub const METRIC_POD_RESTARTS: &str = "k8s.pod.restarts";
pub const METRIC_REQUEST_FAILURE_RATE: &str = "http.server.request.failure_rate";
pub const METRIC_ROLLOUT_STALL_SECONDS: &str = "k8s.deployment.rollout_stall_seconds";
pub const METRIC_NODE_CPU_PERCENT: &str = "node_cpu_percent";
pub const METRIC_POD_RESTART_COUNT: &str = "pod_restart_count";
pub const METRIC_ROLLOUT_STALL_DURATION_SECONDS: &str = "rollout_stall_duration_seconds";
pub const METRIC_HTTP_429_RATE: &str = "http_429_rate";
pub const METRIC_REQUEST_SURGE_RATIO: &str = "request_surge_ratio";
pub const METRIC_BACKEND_FIRST_BYTE_MS: &str = "backend_first_byte_response_time_ms";
pub const METRIC_HEALTHY_HOST_COUNT: &str = "healthy_host_count";
pub const METRIC_MYSQL_CPU_PERCENT: &str = "cpu_percent";
pub const METRIC_MYSQL_ACTIVE_CONNECTIONS: &str = "active_connections";
pub const METRIC_MYSQL_QUERY_COUNT: &str = "Queries";
pub const METRIC_MYSQL_SLOW_QUERY_COUNT: &str = "Slow_queries";
pub const METRIC_APIM_HTTP_5XX_RATE: &str = "http_5xx_rate";
pub const METRIC_APIM_BACKEND_LATENCY_MS: &str = "backend_latency_ms";
pub const METRIC_CONTAINER_APP_CPU_NANOCORES: &str = "container_app_cpu_nanocores";
pub const METRIC_CONTAINER_APP_MEMORY_PERCENT: &str = "container_app_memory_percentage";
pub const METRIC_CONTAINER_APP_REQUEST_TIMEOUTS: &str = "container_app_resiliency_request_timeouts";
pub const METRIC_DEPENDENCY_DURATION_MS: &str = "dependency_duration_ms";
pub const METRIC_SERVICE_REQUEST_DURATION_MS: &str = "service_request_duration_ms";
#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn sre_demo_capture_queries() -> std::collections::BTreeMap<String, String> {
    std::collections::BTreeMap::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn sre_demo_analyzer_queries() -> std::collections::BTreeMap<String, String> {
    std::collections::BTreeMap::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn semantic_investigation_queries() -> std::collections::BTreeMap<String, String> {
    std::collections::BTreeMap::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn resource_metric_queries() -> std::collections::BTreeMap<String, String> {
    std::collections::BTreeMap::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn default_metric_queries() -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    let mut merged: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::<String, String>::new();
    Ok(std::collections::BTreeMap::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn extended_monitor_log_metric_queries(mut include_defaults: bool) -> std::collections::BTreeMap<String, String> {
    std::collections::BTreeMap::new()
}

pub const PUBLIC_EXPORTS: &[&str] = &["METRIC_APIM_BACKEND_LATENCY_MS", "METRIC_CONTAINER_APP_CPU_NANOCORES", "METRIC_CONTAINER_APP_MEMORY_PERCENT", "METRIC_CONTAINER_APP_REQUEST_TIMEOUTS", "METRIC_DEPENDENCY_DURATION_MS", "METRIC_APIM_HTTP_5XX_RATE", "METRIC_BACKEND_FIRST_BYTE_MS", "METRIC_HEALTHY_HOST_COUNT", "METRIC_HOST_CPU_PERCENT", "METRIC_HOST_MEMORY_AVAILABLE_PCT", "METRIC_HTTP_429_RATE", "METRIC_MYSQL_ACTIVE_CONNECTIONS", "METRIC_MYSQL_CPU_PERCENT", "METRIC_MYSQL_QUERY_COUNT", "METRIC_MYSQL_SLOW_QUERY_COUNT", "METRIC_NODE_CPU_PERCENT", "METRIC_POD_RESTART_COUNT", "METRIC_POD_RESTARTS", "METRIC_REQUEST_FAILURE_RATE", "METRIC_REQUEST_SURGE_RATIO", "METRIC_SERVICE_REQUEST_DURATION_MS", "METRIC_ROLLOUT_STALL_SECONDS", "METRIC_ROLLOUT_STALL_DURATION_SECONDS", "default_metric_queries", "extended_monitor_log_metric_queries", "resource_metric_queries", "semantic_investigation_queries", "sre_demo_analyzer_queries", "sre_demo_capture_queries"];
