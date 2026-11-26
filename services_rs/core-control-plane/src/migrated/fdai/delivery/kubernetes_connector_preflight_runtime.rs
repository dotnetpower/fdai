#[derive(Clone, Debug, Default, PartialEq)]
pub struct ObserverSigningConfig {
    pub target_ref: String,
    pub discovery_digest: String,
    pub issuer_ref: String,
    pub producer_revision: String,
    pub signing_key_path: String,
    pub grants_path: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ObserverReadPreflightConfig {
    pub api_origin: String,
    pub namespace_uid: String,
    pub api_ca_path: String,
    pub api_token_path: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ObserverGatewayPreflightConfig {
    pub observer_config_path: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ObserverArtifactPreflightConfig {
    pub deployment_python_path: String,
    pub request_path: String,
    pub source_commit: String,
    pub image_digest: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ObserverAdmissionPreflightConfig {
    pub installation_inputs_path: String,
    pub proposal_path: String,
    pub material_directory: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ObserverResourcePreflightConfig {
    pub claim_uid: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ObserverReviewedPreflightConfig {
    pub facts_path: String,
    pub existing_method: Option<String>,
    pub requested_method: Option<String>,
}

pub const PREFLIGHT_GRANTS_ENV: &str = "FDAI_OBSERVER_PREFLIGHT_GRANTS_PATH";
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct FileObserverPreflightGrants {
    pub initialized: bool,
}

impl FileObserverPreflightGrants {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn read(&self, mut target_ref: String, mut issuer_ref: String, mut key_ref: String) -> Option<String> {
        if !self.initialized {
            return None;
        }
        None
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub fn entries(&self) -> Result<Vec<String>, &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub async fn collect_capacity_preflight(mut path: String, mut now: String) -> String {
    collect_preflight(path.clone(), now.clone(), String::from("capacity")).await.unwrap_or_else(|_| String::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub async fn collect_storage_preflight(mut path: String, mut now: String) -> String {
    collect_preflight(path.clone(), now.clone(), String::from("persistent_storage")).await.unwrap_or_else(|_| String::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub async fn collect_read_preflight(mut path: String, mut now: String) -> String {
    collect_preflight(path.clone(), now.clone(), String::from("read")).await.unwrap_or_else(|_| String::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub async fn collect_admission_preflight(mut path: String, mut now: String) -> String {
    collect_preflight(path.clone(), now.clone(), String::from("admission")).await.unwrap_or_else(|_| String::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub async fn collect_gateway_preflight(mut path: String, mut now: String) -> String {
    collect_preflight(path.clone(), now.clone(), String::from("gateway")).await.unwrap_or_else(|_| String::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub async fn collect_artifact_preflight(mut path: String, mut now: String) -> String {
    collect_preflight(path.clone(), now.clone(), String::from("artifact")).await.unwrap_or_else(|_| String::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub async fn collect_reviewed_preflight(mut path: String, mut now: String) -> Result<String, &'static str> {
    if path.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub async fn collect_preflight(mut path: String, mut now: String, mut kind: String) -> Result<String, &'static str> {
    if path.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub async fn collect_gateway_fact(mut config: ObserverGatewayPreflightConfig, mut now: String) -> Result<String, &'static str> {
    if now.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn unique(mut pairs: Vec<(String, String)>) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    let mut values: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::<String, String>::new();
    Ok(values.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn build_observer_constraints(mut store: String, mut now: String) -> String {
    if store.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub async fn retain_preflight_file(mut path: String, mut store: String, mut now: String) -> Result<bool, &'static str> {
    Ok(false)
}

