pub const DEFAULT_TRACE_LOOKBACK_SECONDS: i64 = 900;
pub const DEFAULT_TICK_BUDGET_SECONDS: i64 = 300;
pub const MAX_TRACE_TOPOLOGIES: i64 = 32;
pub const DEFAULT_LOOP_INTERVAL_SECONDS: i64 = 60;

pub const TARGETS_ENV: &str = "FDAI_ANALYZER_TARGETS";
pub const WINDOW_ENV: &str = "FDAI_ANALYZER_WINDOW_SECONDS";
pub const TRACE_WINDOW_ENV: &str = "FDAI_TRACE_CONTINUITY_WINDOW_SECONDS";
pub const TRACE_LOOKBACK_ENV: &str = "FDAI_TRACE_CONTINUITY_LOOKBACK_SECONDS";
pub const TOPIC_ENV: &str = "FDAI_ANALYZER_TOPIC";
pub const INGRESS_TOPIC_ENV: &str = "KAFKA_TOPIC_EVENTS";
pub const MAX_DISCOVERED_ENV: &str = "FDAI_ANALYZER_MAX_DISCOVERED_TARGETS";
pub const INVENTORY_DSN_ENV: &str = "FDAI_INVENTORY_DSN";
pub const STATE_STORE_DSN_ENV: &str = "FDAI_STATE_STORE_DSN";
pub const TRACE_TOPOLOGIES_ENV: &str = "FDAI_TRACE_TOPOLOGIES_JSON";
pub const LOOP_INTERVAL_ENV: &str = "FDAI_ANALYZER_INTERVAL_SECONDS";
pub const BUDGET_ENV: &str = "FDAI_ANALYZER_BUDGET_SECONDS";
pub const SCHEDULING_MODES: &[&str] = &["one_shot", "local_loop", "container_apps_job", "kubernetes_cronjob"];
pub const TARGET_KEYS: &[&str] = &["resource_id", "kind", "provider_resource_id"];
pub const TRACE_TOPOLOGY_KEYS: &[&str] = &["topology_ref", "resource_ref", "expected_hops"];
#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn resolve_finding_topic(mut environ: std::collections::BTreeMap<String, String>) -> Result<String, &'static str> {
    let topic: String = { let _a = ((environ.clone()).get(TOPIC_ENV).cloned().unwrap_or_else(|| String::from(""))).trim().to_string(); if !_a.is_empty() { _a } else { ((environ.clone()).get(INGRESS_TOPIC_ENV).cloned().unwrap_or_else(|| String::from(""))).trim().to_string() } };
    if (topic.clone()).is_empty() {
        return Err("TOPIC_ENV or INGRESS_TOPIC_ENV is required");
    }
    Ok(topic.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn parse_targets(mut raw: String) -> Result<Vec<String>, &'static str> {
    let text: String = raw.trim().to_string();
    let mut targets: Vec<String> = Vec::<String>::new();
    let mut targets_by_resource: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::<String, String>::new();
    Ok(targets.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn parse_trace_topologies(mut raw: String) -> Result<Vec<String>, &'static str> {
    let text: String = raw.trim().to_string();
    let mut targets: Vec<String> = Vec::<String>::new();
    let mut seen: std::collections::BTreeSet<String> = std::collections::BTreeSet::<String>::new();
    Ok(targets.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn parse_window_seconds(mut raw: String) -> Result<i64, &'static str> {
    let text: String = raw.trim().to_string();
    let window: i64 = (text.clone()).trim().parse::<i64>().unwrap_or(0);
    if !(((1_i64) <= (window)) && ((window) <= (86400_i64))) {
        return Err("WINDOW_ENV MUST be a positive integer");
    }
    Ok(window)
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn resolve_trace_window_seconds(mut environ: std::collections::BTreeMap<String, String>, mut analyzer_window: i64) -> Result<i64, &'static str> {
    let text: String = ((environ.clone()).get(TRACE_WINDOW_ENV).cloned().unwrap_or_else(|| String::from(""))).trim().to_string();
    if (text.clone()).is_empty() {
        return Ok(analyzer_window);
    }
    let window: i64 = (text.clone()).trim().parse::<i64>().unwrap_or(0);
    if !(((1_i64) <= (window)) && ((window) <= (86400_i64))) {
        return Err("TRACE_WINDOW_ENV MUST be a positive integer");
    }
    Ok(window)
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn resolve_trace_lookback_seconds(mut environ: std::collections::BTreeMap<String, String>, mut detection_window: i64) -> Result<i64, &'static str> {
    let text: String = ((environ.clone()).get(TRACE_LOOKBACK_ENV).cloned().unwrap_or_else(|| String::from(""))).trim().to_string();
    if (text.clone()).is_empty() {
        return Ok((DEFAULT_TRACE_LOOKBACK_SECONDS).max(detection_window));
    }
    let lookback: i64 = (text.clone()).trim().parse::<i64>().unwrap_or(0);
    if (lookback) < (detection_window) {
        return Err("TRACE_LOOKBACK_ENV MUST be at least TRACE_WINDOW_ENV");
    }
    Ok(lookback)
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn parse_max_discovered(mut raw: String) -> Result<i64, &'static str> {
    let text: String = raw.trim().to_string();
    let bound: i64 = (text.clone()).trim().parse::<i64>().unwrap_or(0);
    Ok(bound)
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn parse_loop_interval(mut raw: String) -> Result<i64, &'static str> {
    let text: String = raw.trim().to_string();
    if (text.clone()).is_empty() {
        return Ok(DEFAULT_LOOP_INTERVAL_SECONDS);
    }
    let interval: i64 = (text.clone()).trim().parse::<i64>().unwrap_or(0);
    if !(((1_i64) <= (interval)) && ((interval) <= (86400_i64))) {
        return Err("LOOP_INTERVAL_ENV MUST be in 1 86400");
    }
    Ok(interval)
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn parse_tick_budget(mut raw: String) -> Result<i64, &'static str> {
    let text: String = raw.trim().to_string();
    if (text.clone()).is_empty() {
        return Ok(DEFAULT_TICK_BUDGET_SECONDS);
    }
    let budget: i64 = (text.clone()).trim().parse::<i64>().unwrap_or(0);
    if !(((1_i64) <= (budget)) && ((budget) <= (DEFAULT_TICK_BUDGET_SECONDS))) {
        return Err("BUDGET_ENV MUST be in 1 DEFAULT_TICK_BUDGET_SECONDS");
    }
    Ok(budget)
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn metric_source_delays(mut environ: std::collections::BTreeMap<String, String>) -> std::collections::BTreeMap<String, String> {
    std::collections::BTreeMap::from([(String::from("log_analytics"), if !(((environ.clone()).get("FDAI_MONITOR_WORKSPACE_ID").cloned().unwrap_or_else(|| String::from(""))).trim().to_string()).is_empty() { String::from("120-300_seconds") } else { String::from("unbound") }), (String::from("prometheus"), if !(((environ.clone()).get("FDAI_PROMETHEUS_ENDPOINT").cloned().unwrap_or_else(|| String::from(""))).trim().to_string()).is_empty() { String::from("unbound_exact_resource_identity") } else { String::from("unbound") })])
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn resolve_scheduling_mode(mut raw: String) -> Result<String, &'static str> {
    let mode: String = { let _a = raw.trim().to_string(); if !_a.is_empty() { _a } else { String::from("one_shot") } };
    Ok(mode.clone())
}

pub const PUBLIC_EXPORTS: &[&str] = &["BUDGET_ENV", "DEFAULT_MAX_DISCOVERED", "DEFAULT_TICK_BUDGET_SECONDS", "DEFAULT_TRACE_LOOKBACK_SECONDS", "INGRESS_TOPIC_ENV", "INVENTORY_DSN_ENV", "LOOP_INTERVAL_ENV", "MAX_DISCOVERED_ENV", "POD_EVIDENCE_JSON_ENV", "SCHEDULING_MODES", "STATE_STORE_DSN_ENV", "TARGETS_ENV", "TOPIC_ENV", "TRACE_LOOKBACK_ENV", "TRACE_TOPOLOGIES_ENV", "TRACE_WINDOW_ENV", "WINDOW_ENV", "metric_source_delays", "parse_loop_interval", "parse_max_discovered", "parse_targets", "parse_tick_budget", "parse_trace_topologies", "parse_window_seconds", "resolve_finding_topic", "resolve_scheduling_mode", "resolve_trace_lookback_seconds", "resolve_trace_window_seconds"];
