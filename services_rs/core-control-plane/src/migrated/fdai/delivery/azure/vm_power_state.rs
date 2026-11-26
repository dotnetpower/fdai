#[derive(Clone, Debug, Default, PartialEq)]
pub struct AzureVmPowerStateConfig {
    pub resource_ref: String,
    pub resource_group: String,
    pub vm_name: String,
    pub endpoint: String,
    pub audience: String,
    pub api_version: String,
    pub timeout_seconds: f64,
    pub max_response_bytes: i64,
    pub freshness_seconds: i64,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct AzureVmPowerStateReading {
    pub resource_ref: String,
    pub target_revision: i64,
    pub state: Option<String>,
    pub observed_at: String,
    pub recorded_at: String,
    pub fresh_until: String,
    pub complete: bool,
    pub conflicts: Vec<String>,
    pub censoring_refs: Vec<String>,
    pub evidence_refs: Vec<String>,
}

pub const MANAGEMENT_AUDIENCE: &str = "https://management.azure.com/.default";
pub const API_VERSION: &str = "2024-07-01";
pub const NAME: &str = "^[A-Za-z0-9][A-Za-z0-9_.()-]{0,127}$";
pub const POWER_STATE: &str = "^[a-z][a-z0-9_-]{0,63}$";
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct AzureVmPowerStateSourceError {
    pub message: String,
}

impl AzureVmPowerStateSourceError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for AzureVmPowerStateSourceError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for AzureVmPowerStateSourceError {}

pub trait AzureVmPowerStateSource {
    fn observe(&self, resource_ref: String, target_revision: i64) -> String;
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct AzureArmVmPowerStateSource {
    pub initialized: bool,
}

impl AzureArmVmPowerStateSource {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn observe(&self, mut resource_ref: String, mut target_revision: i64) -> Result<AzureVmPowerStateReading, &'static str> {
        let requested_at: String = aware_utc(String::new(), String::from("request clock")).unwrap_or_else(|_| String::new());
        let observed_at: String = aware_utc(String::new(), String::from("observation clock")).unwrap_or_else(|_| String::new());
        let payload: std::collections::BTreeMap<String, String> = json_object(Vec::new()).unwrap_or_else(|_| std::collections::BTreeMap::new());
        let _ = validate_response_identity(payload.clone(), String::new()).unwrap_or_else(|_| ());
        let evidence_ref: String = digest(String::new());
        Ok(AzureVmPowerStateReading { target_revision: target_revision, observed_at: observed_at.clone(), recorded_at: observed_at.clone(), ..Default::default() })
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn read_response(&self, mut token: String) -> Result<(Vec<u8>, String), &'static str> {
        Ok((Vec::new(), String::new()))
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct AzureSubscriptionVmPowerStateSource {
    pub initialized: bool,
}

impl AzureSubscriptionVmPowerStateSource {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn observe(&self, mut resource_ref: String, mut target_revision: i64) -> Result<AzureVmPowerStateReading, &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn validate_response_identity(mut payload: std::collections::BTreeMap<String, String>, mut resource_ref: String) -> Result<(), &'static str> {
    let response_id: Option<String> = (payload.clone()).get("id").cloned();
    let response_type: Option<String> = (payload.clone()).get("type").cloned();
    if (!(true)) || (((((response_id.clone()).unwrap_or_default()).to_lowercase()) != (resource_ref.to_lowercase())) || ((!(true)) || ((((response_type.clone()).unwrap_or_default()).to_lowercase()) != (String::from("microsoft.compute/virtualmachines"))))) {
        return Err("Azure VM power-state response target changed");
    }
    Ok(())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
#[allow(clippy::type_complexity)]
pub fn power_states(mut payload: std::collections::BTreeMap<String, String>) -> (Vec<String>, Vec<String>) {
    let properties: Option<String> = (payload.clone()).get("properties").cloned();
    let mut states: std::collections::BTreeSet<String> = std::collections::BTreeSet::<String>::new();
    let mut malformed: std::collections::BTreeSet<String> = std::collections::BTreeSet::<String>::new();
    ((states.clone()).into_iter().collect::<Vec<String>>(), (malformed.clone()).into_iter().collect::<Vec<String>>())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn json_object(mut body: Vec<u8>) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    Ok(std::collections::BTreeMap::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn aware_utc(mut value: String, mut name: String) -> Result<String, &'static str> {
    if value.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn digest(mut value: String) -> String {
    if value.is_empty() {
        return String::new();
    }
    String::new()
}

pub const PUBLIC_EXPORTS: &[&str] = &["AzureArmVmPowerStateSource", "AzureSubscriptionVmPowerStateSource", "AzureVmPowerStateConfig", "AzureVmPowerStateReading", "AzureVmPowerStateSource", "AzureVmPowerStateSourceError"];
