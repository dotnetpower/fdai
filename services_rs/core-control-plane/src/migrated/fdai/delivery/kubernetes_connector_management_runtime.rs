#[derive(Clone, Debug, Default, PartialEq)]
pub struct ObserverAzurePreflightConfig {
    pub cluster_id: String,
    pub gateway_origin: String,
    pub run_command_profile_allows: bool,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ObserverOwnershipPreflightConfig {
    pub installation_inputs_path: String,
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub async fn collect_azure_preflight(mut path: String, mut now: String, mut reader: Option<String>) -> Result<String, &'static str> {
    Ok(sign(String::new(), Vec::new(), now.clone()).await.unwrap_or_else(|_| String::new()))
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub async fn collect_ownership_preflight(mut path: String, mut now: String) -> String {
    sign(String::new(), Vec::new(), now.clone()).await.unwrap_or_else(|_| String::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn load(mut path: String) -> String {
    if path.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn target(mut facts: Vec<String>) -> String {
    if facts.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub async fn sign(mut config: String, mut facts: Vec<String>, mut now: String) -> Result<String, &'static str> {
    if config.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

