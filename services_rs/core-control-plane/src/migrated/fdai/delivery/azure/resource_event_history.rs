pub const MAX_EVENTS: i64 = 256;
pub const BATCH_SIZE: i64 = 64;

#[derive(Clone, Debug, Default, PartialEq)]
pub struct AzureResourceEventHistoryConfig {
    pub subscription_id: String,
    pub endpoint: String,
    pub timeout_seconds: f64,
    pub max_resources: i64,
    pub max_concurrent_queries: i64,
    pub max_response_bytes: i64,
}

pub const MANAGEMENT_AUDIENCE: &str = "https://management.azure.com/.default";
pub const ARG_API_VERSION: &str = "2022-10-01";
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ResourceEventHistoryError {
    pub message: String,
}

impl ResourceEventHistoryError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for ResourceEventHistoryError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for ResourceEventHistoryError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct AzureResourceEventHistoryReader {
    pub initialized: bool,
}

impl AzureResourceEventHistoryReader {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn read_history(&self, mut resource_ids: Vec<String>, mut event_families: Vec<String>, mut lookback_seconds: i64) -> Result<String, &'static str> {
        if (false) || ((!(true)) || (!(((60_i64) <= (lookback_seconds)) && ((lookback_seconds) <= (86400_i64))))) {
            return Err("Resource event lookback_seconds MUST be in 60 86400");
        }
        let requested: Vec<String> = ((resource_ids.clone()).into_iter().collect::<std::collections::BTreeSet<String>>()).into_iter().collect::<Vec<String>>();
        let mut widened: bool = false;
        let mut malformed: bool = false;
        let mut events: Vec<String> = Vec::<String>::new();
        let mut seen_refs: std::collections::BTreeSet<String> = std::collections::BTreeSet::<String>::new();
        let truncated: bool = (((events.clone()).len() as i64)) > (MAX_EVENTS);
        Ok(self.result(requested.clone(), String::new(), events.clone(), false, None))
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn result(&self, mut resource_ids: Vec<String>, mut observed_at: String, mut events: Vec<String>, mut complete: bool, mut limitation: Option<String>) -> String {
        if !self.initialized {
            return String::new();
        }
        String::new()
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn history_query(mut arm_ids: Vec<String>, mut lookback_seconds: i64) -> String {
    String::from("HealthResources \" \"| where type in~ ('microsoft.resourcehealth/availabilitystatuses', \" \"'microsoft.resourcehealth/resourceannotations') \" f\"| where tostring(properties['targetResourceId']) in~ ({values}) \" f\"| where todatetime(properties['occurredTime']) >= ago({lookback_seconds}s) \" \"| project targetResourceId=tostring(properties['targetResourceId']), \" \"sourceType=tolower(type), \" \"availabilityState=tostring(properties['availabilityState']), \" \"reasonType=tostring(properties['reasonType']), \" \"annotationName=tostring(properties['annotationName']), \" \"context=tostring(properties['context']), \" \"reason=tostring(properties['reason']), \" \"occurredTime=tostring(properties['occurredTime']) \" \"| order by occurredTime asc \" f\"| take {_MAX_EVENTS + 1}")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
#[allow(clippy::type_complexity)]
pub fn chunks(mut values: Vec<String>, mut size: i64) -> Vec<Vec<String>> {
    if values.is_empty() {
        return Vec::new();
    }
    Vec::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn event(mut row: std::collections::BTreeMap<String, String>, mut resource_id: String) -> Option<String> {
    let occurred_at: Option<String> = timestamp(String::new());
    let source_type: Option<String> = (row.clone()).get("sourceType").cloned();
    if (occurred_at.is_none()) || (!(true)) {
        return None;
    }
    let annotation: bool = (((source_type.clone()).unwrap_or_default()).to_lowercase()).ends_with("/resourceannotations");
    let status_source: Option<String> = if annotation { (row.clone()).get("annotationName").cloned() } else { (row.clone()).get("availabilityState").cloned() };
    if (!(true)) || ((((status_source.clone()).unwrap_or_default()).trim().to_string()).is_empty()) {
        return None;
    }
    let reason_source: Option<String> = if annotation { ((row.clone()).get("context").cloned()).or_else(|| (row.clone()).get("reason").cloned()) } else { (row.clone()).get("reasonType").cloned() };
    let classification: String = classification((reason_source.clone()).unwrap_or_default());
    let event_kind: String = if annotation { String::from("resource_annotation") } else { String::from("availability_status") };
    let status: String = machine_token((status_source.clone()).unwrap_or_default(), String::from("unknown"));
    None
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn classification(mut value: String) -> String {
    let folded: String = ({ let _a = value.clone(); if !_a.is_empty() { _a } else { String::from("") } }).to_lowercase();
    if ((folded.clone()).contains("customer")) || ((folded.clone()).contains("user")) {
        return String::from("customer_initiated");
    }
    if (folded.clone()).contains("platform") {
        return String::from("platform_initiated");
    }
    String::from("status_only")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn timestamp(mut value: String) -> Option<String> {
    if (!(true)) || ((value.trim().to_string()).is_empty()) {
        return None;
    }
    None
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn machine_token(mut value: String, mut fallback: String) -> String {
    if (!(true)) || ((value.trim().to_string()).is_empty()) {
        return fallback.clone();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn kusto_literal(mut value: String) -> String {
    (value.clone()).replace("'", "''")
}

pub const PUBLIC_EXPORTS: &[&str] = &["AzureResourceEventHistoryConfig", "AzureResourceEventHistoryReader", "ResourceEventHistoryError"];
