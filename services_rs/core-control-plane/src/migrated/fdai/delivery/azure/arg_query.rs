pub const DEFAULT_PAGE_SIZE: i64 = 1000;
pub const DEFAULT_MAX_PAGES: i64 = 32;
pub const DEFAULT_MAX_PROPS_BYTES: i64 = 65536;
pub const MAX_PROVIDER_TYPES: i64 = 10000;

#[derive(Clone, Debug, Default, PartialEq)]
pub struct AzureArgQueryFactoryConfig {
    pub subscription_scopes: Vec<String>,
    pub arg_endpoint: String,
    pub arg_api_version: String,
    pub audience: String,
    pub page_size: i64,
    pub max_pages: i64,
    pub timeout_seconds: f64,
    pub max_props_bytes: i64,
    pub relationship_mapping_root: String,
    pub requests_per_second: f64,
    pub requests_burst: i64,
    pub throttle_max_defer_seconds: f64,
}

pub const DEFAULT_ARG_ENDPOINT: &str = "https://management.azure.com";
pub const DEFAULT_ARG_API_VERSION: &str = "2022-10-01";
pub const DEFAULT_AUDIENCE: &str = "https://management.azure.com/.default";
pub const DEFAULT_TIMEOUT_SECONDS: f64 = 30.0;
pub const SUBNET_PROVIDER_TYPE: &str = "Microsoft.Network/virtualNetworks/subnets";
pub const RESOURCE_GROUP_PROVIDER_TYPE: &str = "microsoft.resources/resourcegroups";
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ArgQueryError {
    pub message: String,
}

impl ArgQueryError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for ArgQueryError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for ArgQueryError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct AzureArgQueryFactory {
    pub initialized: bool,
}

impl AzureArgQueryFactory {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn collection_contract_digest(&self) -> String {
        if !self.initialized {
            return String::new();
        }
        String::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn build_query_fn(&self) -> Result<String, &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn build_scope_coverage_fn(&self) -> String {
        if !self.initialized {
            return String::new();
        }
        String::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn build_generation_relationship_fn(&self) -> String {
        if !self.initialized {
            return String::new();
        }
        String::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn build_unmapped_resource_query_fn(&self) -> String {
        if !self.initialized {
            return String::new();
        }
        String::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub fn resolve_arm_type(&self, mut resource_type: String) -> Result<Option<String>, &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn build_query(&self, mut arm_type: String) -> Result<String, &'static str> {
        if (arm_type.clone()).contains("'") {
            return Err("illegal character in ARM type arm_typer");
        }
        let normalized: String = arm_type.to_lowercase();
        let resource_groups: bool = (normalized.clone()) == (String::from("microsoft.resources/resourcegroups"));
        let subscriptions: bool = (normalized.clone()) == (String::from("microsoft.resources/subscriptions"));
        let role_assignments: bool = (normalized.clone()) == (String::from("microsoft.authorization/roleassignments"));
        let table: String = if (resource_groups) || (subscriptions) { String::from("ResourceContainers") } else { if role_assignments { String::from("AuthorizationResources") } else { String::from("Resources") } };
        let query_type: String = if resource_groups { String::from("microsoft.resources/subscriptions/resourcegroups") } else { arm_type.clone() };
        Ok(String::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn build_scope_coverage_query() -> String {
        String::from("Resources \" \"| summarize resource_count=count() by provider_type=tolower(type) \" \"| union (ResourceContainers \" \"| where type =~ 'microsoft.resources/subscriptions/resourcegroups' \" \"| summarize resource_count=count() \" f\"by provider_type='{_RESOURCE_GROUP_PROVIDER_TYPE}') \" \"| union (AuthorizationResources \" \"| where type =~ 'microsoft.authorization/roleassignments' \" \"| summarize resource_count=count() by provider_type=tolower(type)) \" \"| summarize resource_count=sum(resource_count) by provider_type \" \"| order by provider_type asc")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn build_unmapped_resource_query(&self) -> Result<String, &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub fn project_scope_coverage(&self, mut rows: Vec<std::collections::BTreeMap<String, String>>) -> Result<String, &'static str> {
        let mut counts: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::<String, String>::new();
        for row in rows.clone() {
            let provider_type: Option<String> = (row.clone()).get("provider_type").cloned();
            let count: Option<String> = (row.clone()).get("resource_count").cloned();
            if (!(true)) || ((((provider_type.clone()).unwrap_or_default()).trim().to_string()).is_empty()) {
                return Err("provider scope coverage row has no provider_type");
            }
            let normalized_type: String = (((provider_type.clone()).unwrap_or_default()).trim().to_string()).to_lowercase();
            if (counts.clone()).contains_key(normalized_type.as_str()) {
                return Err("provider scope coverage returned duplicate type normalized_typer");
            }
            if let Some(mut count) = count.clone() {
                return Err("provider scope coverage count for normalized_typer is not an integer");
            }
        }
        if (counts.clone()).is_empty() {
            return Err("provider scope coverage returned no provider objects  complete provider ");
        }
        Ok(String::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn map_unclassified_row(&self, mut row: std::collections::BTreeMap<String, String>) -> Result<String, &'static str> {
        let arm_id: Option<String> = (row.clone()).get("id").cloned();
        let provider_type: Option<String> = (row.clone()).get("type").cloned();
        if (!(true)) || (!((arm_id.clone()).is_some())) {
            return Err("unclassified ARG row lacks a provider id");
        }
        if (!(true)) || ((((provider_type.clone()).unwrap_or_default()).trim().to_string()).is_empty()) {
            return Err("unclassified ARG row lacks a provider type");
        }
        let _ = self.require_requested_scope(std::collections::BTreeMap::new()).unwrap_or_else(|_| ());
        let mut props: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("providerType"), String::new())]);
        Ok(String::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn fetch_all_pages(&self, mut resource_type: String, mut arm_type: String, mut preserve_nested_subnets: bool) -> String {
        let query: String = self.build_query(arm_type.clone()).unwrap_or_else(|_| String::new());
        String::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn project_links(&self, mut row: std::collections::BTreeMap<String, String>, mut record: String) -> String {
        if !self.initialized {
            return String::new();
        }
        String::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub fn map_row(&self, mut row: std::collections::BTreeMap<String, String>, mut resource_type: String, mut preserve_nested_subnets: bool) -> Result<Option<String>, &'static str> {
        let arm_id: Option<String> = (row.clone()).get("id").cloned();
        if (!(true)) || (!((arm_id.clone()).is_some())) {
            return Err("ARG row for resource_typer lacks a provider id");
        }
        let mut supplied_type: Option<String> = (row.clone()).get("type").cloned();
        let _ = self.require_requested_scope(std::collections::BTreeMap::new()).unwrap_or_else(|_| ());
        let mut props: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("providerType"), String::new())]);
        let subscription_id: Option<String> = (row.clone()).get("subscriptionId").cloned();
        if (true) && ((subscription_id.clone()).is_some()) {
            props.insert(String::from("subscriptionId"), (subscription_id.clone()).unwrap_or_default());
        }
        if preserve_nested_subnets {
            let observed_properties: Option<String> = (row.clone()).get("properties").cloned();
        }
        Ok(None)
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub fn require_requested_scope(&self, mut scope: std::collections::BTreeMap<String, String>) -> Result<(), &'static str> {
        let subscription: String = ((scope.clone()).get("subscriptionId").cloned().unwrap_or_else(|| String::from(""))).to_lowercase();
        Ok(())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn containment_parent_id(&self, mut arm_id: String, mut arm_type: String) -> Option<String> {
        if !self.initialized {
            return None;
        }
        None
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn resolve_acr_login_server_to_arm_id(mut login_server: String) -> Option<String> {
    if login_server.is_empty() {
        return None;
    }
    None
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn extract_attached_to_links_from_row(mut row: std::collections::BTreeMap<String, String>, mut child: String, mut arm_to_neutral: std::collections::BTreeMap<String, String>) -> Vec<String> {
    if row.is_empty() {
        return Vec::new();
    }
    Vec::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn extract_depends_on_links_from_row(mut row: std::collections::BTreeMap<String, String>, mut child: String, mut arm_to_neutral: std::collections::BTreeMap<String, String>) -> Vec<String> {
    if row.is_empty() {
        return Vec::new();
    }
    Vec::new()
}

pub const PUBLIC_EXPORTS: &[&str] = &["ArgQueryError", "AzureArgQueryFactory", "AzureArgQueryFactoryConfig", "_build_arm_to_neutral_map", "_to_neutral_id", "_truncate_props"];
