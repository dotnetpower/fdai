pub const SOURCE_CORE: &str = "core-control-plane";
#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn targets_configured(mut raw: String) -> bool {
    if raw.is_empty() {
        return false;
    }
    false
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn forecast_history_projection(mut env: std::collections::BTreeMap<String, String>) -> std::collections::BTreeMap<String, String> {
    let targets: bool = targets_configured(((env.clone()).get("FDAI_FORECAST_TARGETS_JSON").cloned().unwrap_or_else(|| String::from(""))).trim().to_string());
    let sources_raw: String = ((env.clone()).get("FDAI_FORECAST_HISTORY_SOURCES_JSON").cloned().unwrap_or_else(|| String::from(""))).trim().to_string();
    let producers_raw: String = ((env.clone()).get("FDAI_FORECAST_HISTORY_PRODUCERS_JSON").cloned().unwrap_or_else(|| String::from(""))).trim().to_string();
    let configured: bool = (!(sources_raw.clone()).is_empty()) || (!(producers_raw.clone()).is_empty());
    let mut configuration: Option<String> = None;
    let mut invalid: bool = (!(producers_raw.clone()).is_empty()) && ((sources_raw.clone()).is_empty());
    std::collections::BTreeMap::from([(String::from("key"), String::from("forecast-history")), (String::from("source"), String::from(SOURCE_CORE)), (String::from("observed"), String::new()), (String::from("configured"), String::new()), (String::from("ready"), String::new()), (String::from("mode"), String::from("disabled")), (String::from("reason"), String::from("configuration is invalid\" if invalid else _UNAVAILABLE if collection_available else \"configuration is incomplete\" if configured else \"not configured")), (String::from("available"), String::new()), (String::from("collection_available"), String::new()), (String::from("enabled"), String::new()), (String::from("enabled_source"), String::from("durable_settings")), (String::from("authority_mode"), String::from("shadow")), (String::from("scoring_authority"), String::new()), (String::from("execution_authority"), String::new()), (String::from("unavailable_reason"), String::new()), (String::from("prerequisites"), String::new()), (String::from("sources"), String::new())])
}

pub const PUBLIC_EXPORTS: &[&str] = &["forecast_history_projection"];
