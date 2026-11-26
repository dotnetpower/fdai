use std::collections::BTreeMap;
#[derive(Clone, Debug, Default, PartialEq)]
pub struct GatewayPrincipal {
    pub object_id: String,
    pub groups: Vec<String>,
    pub roles: Vec<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct PrivateProbe {
    pub url: String,
    pub audience: String,
    pub result_contract: String,
}

impl PrivateProbe {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.url.trim().is_empty() { return Err("url must be non-empty"); }
        if self.audience.trim().is_empty() { return Err("audience must be non-empty"); }
        if self.result_contract.trim().is_empty() { return Err("result_contract must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct GatewayConfig {
    pub subscription_id: String,
    pub resource_groups: Vec<String>,
    pub contributor_group_id: String,
    pub executor_principal_ids: String,
    pub reader_identity_client_id: String,
    pub executor_identity_client_id: String,
    pub idempotency_container_url: String,
    pub private_probes: BTreeMap<String, PrivateProbe>,
    pub mutations_enabled: bool,
}

pub const ARM_AUDIENCE: &str = "https://management.azure.com";
pub const NETWORK_API_VERSION: &str = "2025-05-01";
pub const COMPUTE_API_VERSION: &str = "2025-04-01";
pub const TAGS_API_VERSION: &str = "2021-04-01";
pub const IDENTIFIER: &str = "^[A-Za-z0-9][A-Za-z0-9_.()-]{0,127}$";
pub const TAG_NAME: &str = "^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$";
pub const TAG_VALUE: &str = "^[A-Za-z0-9][A-Za-z0-9_.:@ -]{0,255}$";
pub const EXECUTOR_VERTICAL_ORDER: &[&str] = &["change", "resilience", "finops"];
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct GatewayError {
    pub message: String,
}

impl GatewayError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for GatewayError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for GatewayError {}

impl GatewayConfig {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub fn from_env(mut env: Option<std::collections::BTreeMap<String, String>>) -> Result<GatewayConfig, &'static str> {
        let mut probes: std::collections::BTreeMap<String, PrivateProbe> = std::collections::BTreeMap::<String, PrivateProbe>::new();
        Err("runtime_binding_required")
    }
}

pub trait TokenProvider {
    fn get_token(&self, audience: String) -> String;
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ManagedIdentityTokenProvider {
    pub initialized: bool,
}

impl ManagedIdentityTokenProvider {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn get_token(&self, mut audience: String) -> Result<String, &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
}

