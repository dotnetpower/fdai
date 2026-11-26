pub const DOTNET_UNIX_EPOCH_TICKS: i64 = 621355968000000000;
pub const DOTNET_TICKS_PER_MICROSECOND: i64 = 10;

#[derive(Clone, Debug, Default, PartialEq)]
pub struct AzureServiceHealthConfig {
    pub subscription_id: String,
    pub endpoint: String,
    pub timeout_seconds: f64,
    pub max_events: i64,
    pub max_impacts: i64,
    pub max_response_bytes: i64,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Event {
    pub aliases: Vec<String>,
    pub event_id: String,
    pub event_type: String,
    pub title: String,
    pub level: Option<String>,
    pub status: String,
    pub impact_start_at: String,
    pub evidence_ref: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Impact {
    pub event_alias: String,
    pub resource_ref: String,
    pub resource_name: Option<String>,
    pub resource_type: Option<String>,
    pub resource_group: Option<String>,
    pub region: Option<String>,
    pub status: Option<String>,
    pub evidence_ref: String,
}

pub const MANAGEMENT_AUDIENCE: &str = "https://management.azure.com/.default";
pub const ARG_API_VERSION: &str = "2022-10-01";
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ServiceHealthError {
    pub message: String,
}

impl ServiceHealthError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for ServiceHealthError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for ServiceHealthError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct AzureServiceHealthReader {
    pub initialized: bool,
}

impl AzureServiceHealthReader {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn read_active(&self) -> Result<String, &'static str> {
        let mut events: Vec<String> = Vec::<String>::new();
        let mut seen_event_refs: std::collections::BTreeSet<String> = std::collections::BTreeSet::<String>::new();
        let mut malformed: bool = false;
        if (events.clone()).is_empty() {
            return Ok(self.result(String::new(), Vec::new(), false, None));
        }
        let mut alias_owner: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::<String, String>::new();
        let mut ambiguous_alias: bool = false;
        let mut impact_unavailable: bool = false;
        let mut widened: bool = false;
        let mut impact_malformed: bool = false;
        let mut observations: Vec<String> = Vec::<String>::new();
        Ok(self.result(String::new(), observations.clone(), false, None))
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn query(&self, mut query: String, mut result_name: String, mut record_limit: i64) -> Vec<std::collections::BTreeMap<String, String>> {
        if !self.initialized {
            return Vec::new();
        }
        Vec::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn result(&self, mut observed_at: String, mut observations: Vec<String>, mut complete: bool, mut limitation: Option<String>) -> String {
        if !self.initialized {
            return String::new();
        }
        String::new()
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn active_events_query(mut max_events: i64) -> String {
    String::from("ServiceHealthResources \" \"| where type =~ 'microsoft.resourcehealth/events' \" \"| where tostring(properties['Status']) =~ 'Active' \" \"| project eventName=tostring(name), \" \"trackingId=tostring(properties['TrackingId']), \" \"eventType=tostring(properties['EventType']), \" \"status=tostring(properties['Status']), \" \"level=tostring(properties['Level']), \" \"title=tostring(properties['Title']), \" \"impactStartTime=tostring(properties['ImpactStartTime']) \" \"| order by impactStartTime asc \" f\"| take {max_events + 1}")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn active_impacts_query(mut aliases: Vec<String>, mut max_impacts: i64) -> String {
    String::from("ServiceHealthResources \" \"| where type =~ 'microsoft.resourcehealth/events/impactedresources' \" \"| extend parentEventId=tostring(split(id, '/impactedResources/')[0]) \" \"| extend eventTrackingId=tostring(split(parentEventId, '/events/')[1]) \" f\"| where eventTrackingId in~ ({values}) \" \"| project eventTrackingId, \" \"targetResourceId=tostring(properties['targetResourceId']), \" \"resourceName=tostring(properties['resourceName']), \" \"resourceGroup=tostring(properties['resourceGroup']), \" \"targetResourceType=tostring(properties['targetResourceType']), \" \"targetRegion=tostring(properties['targetRegion']), \" \"status=tostring(properties['status']) \" f\"| take {max_impacts + 1}")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
#[allow(clippy::type_complexity)]
pub fn event(mut row: std::collections::BTreeMap<String, String>, mut observed_at: String) -> (Option<String>, bool) {
    let tracking_id: Option<String> = bounded_text(String::new(), 256_i64);
    let event_name: Option<String> = bounded_text(String::new(), 256_i64);
    let event_type_raw: Option<String> = bounded_text(String::new(), 64_i64);
    let status_raw: Option<String> = bounded_text(String::new(), 64_i64);
    let impact_start_at: Option<String> = timestamp(String::new());
    let status: String = machine_token((status_raw.clone()).unwrap_or_default());
    if ((impact_start_at.clone()).unwrap_or_default()) > (observed_at.clone()) {
        return (None, true);
    }
    let title: String = (bounded_text(String::new(), 512_i64)).unwrap_or_else(|| (event_name.clone()).unwrap_or_default());
    if false {
        return (None, false);
    }
    let level_raw: Option<String> = bounded_text(String::new(), 64_i64);
    (None, false)
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn impact(mut row: std::collections::BTreeMap<String, String>) -> Option<String> {
    let event_alias: Option<String> = bounded_text(String::new(), 256_i64);
    let target_resource_id: Option<String> = bounded_text(String::new(), 2048_i64);
    if (event_alias.is_none()) || (target_resource_id.is_none()) {
        return None;
    }
    None
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn observation(mut event: String, mut observed_at: String, mut impact: Option<String>, mut impact_count: Option<i64>) -> String {
    if event.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn impact_scope_state(mut value: String, mut subscription_id: String) -> String {
    if (false) || ((value.clone()) == (String::from(""))) {
        return String::from("valid");
    }
    if (!(true)) || ((((value.clone()).len() as i64)) > (2048_i64)) {
        return String::from("malformed");
    }
    let root: String = (format!("/subscriptions/{}", subscription_id.clone())).to_lowercase();
    String::from("valid\" if folded == root or folded.startswith(f\"{root}/\") else \"widened")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn bounded_text(mut value: String, mut maximum: i64) -> Option<String> {
    if !(true) {
        return None;
    }
    let normalized: String = value.trim().to_string();
    if (!(normalized.clone()).is_empty()) && ((((normalized.clone()).len() as i64)) <= (maximum)) { Some(normalized.clone()) } else { None }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn timestamp(mut value: String) -> Option<String> {
    if value.is_empty() {
        return None;
    }
    None
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn alphanumeric(mut value: String) -> String {
    if value.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn machine_token(mut value: String) -> String {
    String::from("_\".join(value.casefold().replace(\"-\", \" \").split())[:64] or \"unknown")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn kusto_literal(mut value: String) -> String {
    (value.clone()).replace("'", "''")
}

pub const PUBLIC_EXPORTS: &[&str] = &["AzureServiceHealthConfig", "AzureServiceHealthReader", "ServiceHealthError"];
