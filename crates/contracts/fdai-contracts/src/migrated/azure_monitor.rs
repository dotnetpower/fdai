use std::collections::BTreeMap;
pub const MAX_ALERT_TARGETS: i64 = 32;
pub const MAX_TEXT: i64 = 512;

#[derive(Clone, Debug, Default, PartialEq)]
pub struct AzureMonitorEvent {
    pub schema_version: String,
    pub event_id: String,
    pub idempotency_key: String,
    pub correlation_id: String,
    pub source: String,
    pub event_type: String,
    pub resource_ref: String,
    pub payload: BTreeMap<String, String>,
    pub detected_at: String,
    pub ingested_at: String,
    pub incident_correlation: String,
    pub tier: String,
    pub decision: String,
    pub mode: String,
}

impl AzureMonitorEvent {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.schema_version.as_str(), "1.0.0") { return Err("invalid schema_version literal"); }
        if !matches!(self.source.as_str(), "azure_monitor_metric_alert") { return Err("invalid source literal"); }
        if !matches!(self.event_type.as_str(), "metric_alert_fired" | "metric_alert_resolved") { return Err("invalid event_type literal"); }
        if !matches!(self.incident_correlation.as_str(), "correlate") { return Err("invalid incident_correlation literal"); }
        if !matches!(self.mode.as_str(), "shadow") { return Err("invalid mode literal"); }
        Ok(())
    }
}

pub const COMMON_ALERT_SCHEMA: &str = "azureMonitorCommonAlertSchema";
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct AzureMonitorNormalizationError {
    pub message: String,
}

impl AzureMonitorNormalizationError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for AzureMonitorNormalizationError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for AzureMonitorNormalizationError {}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn normalize_common_alert_schema(mut payload: std::collections::BTreeMap<String, String>, mut ingested_at: String) -> Result<Vec<AzureMonitorEvent>, &'static str> {
    if ((payload.clone()).get("schemaId").cloned()) != Some(String::from(COMMON_ALERT_SCHEMA)) {
        return Err("unsupported Azure Monitor alert schema");
    }
    let data: std::collections::BTreeMap<String, String> = mapping(String::new(), String::from("data")).unwrap_or_else(|_| std::collections::BTreeMap::new());
    let essentials: std::collections::BTreeMap<String, String> = mapping(String::new(), String::from("data.essentials")).unwrap_or_else(|_| std::collections::BTreeMap::new());
    let alert_id: String = text(essentials.clone(), String::from("alertId")).unwrap_or_else(|_| String::new());
    let condition: String = text(essentials.clone(), String::from("monitorCondition")).unwrap_or_else(|_| String::new());
    let normalized_condition: String = (condition.clone()).to_lowercase();
    if !(matches!(normalized_condition.as_str(), "fired" | "resolved")) {
        return Err("monitorCondition MUST be Fired or Resolved");
    }
    let targets: Vec<String> = string_sequence(String::new(), String::from("alertTargetIDs")).unwrap_or_else(|_| Vec::new());
    if !(((1_i64) <= (((targets.clone()).len() as i64))) && ((((targets.clone()).len() as i64)) <= (MAX_ALERT_TARGETS))) {
        return Err("alertTargetIDs MUST contain 1 to _MAX_ALERT_TARGETS values");
    }
    let alert_digest: String = digest(alert_id.clone());
    let correlation_id: String = format!("azure-alert:{}", alert_digest.clone());
    let stable_payload: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("alert_rule_digest"), digest(text(essentials.clone(), String::from("alertRule")).unwrap_or_else(|_| String::new()))), (String::from("severity"), text(essentials.clone(), String::from("severity")).unwrap_or_else(|_| String::new())), (String::from("monitor_condition"), normalized_condition.clone()), (String::from("signal_type"), text(essentials.clone(), String::from("signalType")).unwrap_or_else(|_| String::new())), (String::from("monitoring_service"), text(essentials.clone(), String::from("monitoringService")).unwrap_or_else(|_| String::new()))]);
    let mut events: Vec<AzureMonitorEvent> = Vec::<AzureMonitorEvent>::new();
    Ok(events.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn to_neutral_id(mut arm_id: String) -> Result<String, &'static str> {
    let trimmed: String = arm_id.trim().to_string();
    let marker: String = String::from("/resourcegroups/");
    let folded: String = (trimmed.clone()).to_lowercase();
    Ok(String::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn mapping(mut value: String, mut field: String) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    if !(false) {
        return Err("field MUST be an object");
    }
    Ok(std::collections::BTreeMap::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn text(mut values: std::collections::BTreeMap<String, String>, mut field: String) -> Result<String, &'static str> {
    let value: Option<String> = (values.clone()).get(field.as_str()).cloned();
    if (!(true)) || (((((value.clone()).unwrap_or_default()).trim().to_string()).is_empty()) || ((((((value.clone()).unwrap_or_default()).trim().to_string()).len() as i64)) > (MAX_TEXT))) {
        return Err("field MUST contain 1 to _MAX_TEXT characters");
    }
    Ok(((value.clone()).unwrap_or_default()).trim().to_string())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn string_sequence(mut value: String, mut field: String) -> Result<Vec<String>, &'static str> {
    if (!(false)) || (true) {
        return Err("field MUST be an array of strings");
    }
    let mut result: Vec<String> = Vec::<String>::new();
    Ok(result.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn timestamp(mut values: std::collections::BTreeMap<String, String>, mut field: String) -> Result<String, &'static str> {
    let raw: String = text(values.clone(), field.clone()).unwrap_or_else(|_| String::new());
    Ok(String::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn digest(mut value: String) -> String {
    if value.is_empty() {
        return String::new();
    }
    String::new()
}

pub const PUBLIC_EXPORTS: &[&str] = &["AzureMonitorEvent", "AzureMonitorNormalizationError", "normalize_common_alert_schema"];
