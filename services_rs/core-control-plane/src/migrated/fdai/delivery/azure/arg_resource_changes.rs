pub const DEFAULT_MAX_PROPS_BYTES: i64 = 65536;
pub const DEFAULT_INITIAL_LOOKBACK_SECONDS: i64 = 3600;
pub const DEFAULT_PAGE_SIZE: i64 = 200;
pub const DEFAULT_MAX_PAGES: i64 = 5;
pub const DEFAULT_MAX_HYDRATION_BATCH: i64 = 100;
pub const MAX_HYDRATION_BATCH_CAP: i64 = 100;
pub const DEFAULT_MAX_RESPONSE_BYTES: i64 = 10000000;
pub const DEFAULT_MAX_TOTAL_RESPONSE_BYTES: i64 = 64000000;

#[derive(Clone, Debug, Default, PartialEq)]
pub struct AzureResourceChangeFeedConfig {
    pub subscription_scope: String,
    pub arg_endpoint: String,
    pub arg_api_version: String,
    pub audience: String,
    pub timeout_seconds: f64,
    pub max_props_bytes: i64,
    pub initial_lookback_seconds: i64,
    pub page_size: i64,
    pub max_pages: i64,
    pub max_hydration_batch: i64,
    pub max_hydration_retries: i64,
    pub max_response_bytes: i64,
    pub max_total_response_bytes: i64,
    pub requests_per_second: f64,
    pub relationship_mapping_root: String,
}

pub const DEFAULT_ARG_ENDPOINT: &str = "https://management.azure.com";
pub const DEFAULT_ARG_API_VERSION: &str = "2022-10-01";
pub const DEFAULT_AUDIENCE: &str = "https://management.azure.com/.default";
pub const DEFAULT_TIMEOUT_SECONDS: f64 = 30.0;
pub const INITIAL_CURSOR_ID: &str = "__fdai_initial__";
pub const SOURCE: &str = "fdai.delivery.azure.arg_resource_changes";
pub const SIGNAL_KIND: &str = "azure.resource_graph_change_feed";
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct AzureResourceChangeFeed {
    pub initialized: bool,
}

impl AzureResourceChangeFeed {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn initial_cursor(&self) -> Result<String, &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn max_hydration_retries(&self) -> i64 {
        0_i64
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn poll(&self, mut cursor: String) -> Result<String, &'static str> {
        let query: String = self.build_change_query(None, None).unwrap_or_else(|_| String::new());
        let tokenless_truncated: bool = false;
        let mut latest_by_resource: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::<String, String>::new();
        let mut events: Vec<String> = Vec::<String>::new();
        let mut published_cursors: Vec<String> = Vec::<String>::new();
        let hydration: String = self.hydrate(Vec::new()).await;
        let mut hydration_incomplete: bool = false;
        Ok(String::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn build_change_query(&self, mut lower_ts: Option<String>, mut lower_id: Option<String>) -> Result<String, &'static str> {
        if (lower_ts.is_none()) || (lower_id.is_none()) {
            return Err("resourcechanges cursor initialization failed");
        }
        Ok(String::from("resourcechanges \" \"| extend changeTime = todatetime(properties.changeAttributes.timestamp), \" \"changeType = tostring(properties.changeType), \" \"targetResourceId = tostring(properties.targetResourceId), \" \"targetResourceType = tostring(properties.targetResourceType), \" \"changes = properties.changes \" f\"{predicate}\" \"| order by changeTime asc, id asc \" \"| project id, changeTime, changeType, targetResourceId, targetResourceType, changes"))
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn build_hydration_query(&self, mut arm_ids: Vec<String>) -> Result<String, &'static str> {
        for arm_id in arm_ids.clone() {
            if (arm_id.clone()).contains("'") {
                return Err("illegal character in resourcechanges target id");
            }
        }
        Ok(String::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn parse_change_row(&self, mut row: std::collections::BTreeMap<String, String>) -> Result<String, &'static str> {
        let change_id: Option<String> = (row.clone()).get("id").cloned();
        if (!(true)) || (!((change_id.clone()).is_some())) {
            return Err("resourcechanges row lacks an id");
        }
        let raw_kind: Option<String> = (row.clone()).get("changeType").cloned();
        if (!(true)) || ((((raw_kind.clone()).unwrap_or_default()).trim().to_string()).is_empty()) {
            return Err("resourcechanges row changeType MUST be a string");
        }
        let arm_id: Option<String> = (row.clone()).get("targetResourceId").cloned();
        if (!(true)) || (!(((arm_id.clone()).unwrap_or_default()).starts_with("/"))) {
            return Err("resourcechanges row targetResourceId MUST be an ARM id");
        }
        let arm_type: Option<String> = (row.clone()).get("targetResourceType").cloned();
        if (arm_type.is_some()) && (!(true)) {
            return Err("resourcechanges row targetResourceType MUST be a string or null");
        }
        let raw_changes: Option<String> = (row.clone()).get("changes").cloned();
        if (raw_changes.is_some()) && (!(true)) {
            return Err("resourcechanges row changes MUST be an object or null");
        }
        Ok(String::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn resolve_delete_type(&self, mut change: String) -> Option<String> {
        if !self.initialized {
            return None;
        }
        None
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn hydrate(&self, mut arm_ids: Vec<String>) -> String {
        let mut hydrated: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::<String, String>::new();
        let mut seen_provider_refs: std::collections::BTreeSet<String> = std::collections::BTreeSet::<String>::new();
        String::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub fn map_hydrated_row(&self, mut row: std::collections::BTreeMap<String, String>) -> Result<Option<(String, String)>, &'static str> {
        let arm_id: Option<String> = (row.clone()).get("id").cloned();
        if (!(true)) || (!((arm_id.clone()).is_some())) {
            return Err("resourcechanges hydration row lacks a provider id");
        }
        let mut arm_type: Option<String> = (row.clone()).get("type").cloned();
        if (!(true)) || ((((arm_type.clone()).unwrap_or_default()).trim().to_string()).is_empty()) {
            return Err("resourcechanges hydration row lacks a provider type");
        }
        let mut props: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("providerType"), (arm_type.clone()).unwrap_or_default())]);
        let subscription_id: Option<String> = (row.clone()).get("subscriptionId").cloned();
        if (true) && ((subscription_id.clone()).is_some()) {
            props.insert(String::from("subscriptionId"), (subscription_id.clone()).unwrap_or_default());
        }
        props.insert(String::from("providerType"), (arm_type.clone()).unwrap_or_default());
        Ok(None)
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn upsert_event(&self, mut change: String, mut record: String) -> String {
        let resource_payload: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("resource_id"), String::new()), (String::from("type"), String::new()), (String::from("props"), String::new()), (String::from("provider_ref"), String::new()), (String::from("last_seen"), String::new())]);
        String::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn tombstone_event(&self, mut change: String, mut resource_type: String) -> String {
        let resource_payload: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("resource_id"), String::new()), (String::from("type"), resource_type.clone()), (String::from("props"), String::new()), (String::from("provider_ref"), String::new()), (String::from("last_seen"), String::new())]);
        String::new()
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["ArgResourceChangeError", "AzureResourceChangeFeed", "AzureResourceChangeFeedConfig", "DEFAULT_RESOURCE_CHANGE_DEADLINE_SECONDS", "ResourceChangeFeedResult", "forward_arg_resource_changes"];
