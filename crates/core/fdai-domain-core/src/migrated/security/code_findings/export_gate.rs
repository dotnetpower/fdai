#[derive(Clone, Debug, Default, PartialEq)]
pub struct ApprovedAgentProvider {
    pub provider_id: String,
    pub display_name: String,
    pub modes: Vec<String>,
    pub data_residency: String,
    pub training_use: String,
    pub retention_days: i64,
    pub approved_until: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct AgentProviderPolicy {
    pub version: String,
    pub providers: Vec<ApprovedAgentProvider>,
}

pub const PROVIDER_ID: &str = "^[a-z][a-z0-9.-]{1,63}$";
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ExportDeniedError {
    pub message: String,
}

impl ExportDeniedError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for ExportDeniedError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for ExportDeniedError {}

impl AgentProviderPolicy {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn from_mapping(mut document: std::collections::BTreeMap<String, String>) -> Result<AgentProviderPolicy, &'static str> {
        let allowed: std::collections::BTreeSet<String> = std::collections::BTreeSet::from([String::from("schema_version"), String::from("version"), String::from("providers")]);
        let mut providers: Vec<ApprovedAgentProvider> = Vec::<ApprovedAgentProvider>::new();
        Err("runtime_binding_required")
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn authorize_export(mut policy: AgentProviderPolicy, mut provider_id: String, mut mode: String, mut today: String) -> Result<ApprovedAgentProvider, &'static str> {
    if provider_id.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

pub const PUBLIC_EXPORTS: &[&str] = &["AgentProviderPolicy", "ApprovedAgentProvider", "ExportDeniedError", "authorize_export"];
