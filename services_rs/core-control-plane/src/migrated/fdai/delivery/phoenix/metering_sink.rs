pub const NS_PER_MS: i64 = 1000000;

#[derive(Clone, Debug, Default, PartialEq)]
pub struct PhoenixTracingConfig {
    pub endpoint: String,
    pub project_name: String,
    pub capture_content: bool,
}

impl PhoenixTracingConfig {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.endpoint.trim().is_empty() { return Err("endpoint must be non-empty"); }
        if self.project_name.trim().is_empty() { return Err("project_name must be non-empty"); }
        Ok(())
    }
}

pub const ENABLED_ENV: &str = "FDAI_PHOENIX_TRACING_ENABLED";
pub const ENDPOINT_ENV: &str = "FDAI_PHOENIX_OTLP_ENDPOINT";
pub const PROJECT_ENV: &str = "FDAI_PHOENIX_PROJECT_NAME";
pub const CAPTURE_CONTENT_ENV: &str = "FDAI_PHOENIX_CAPTURE_CONTENT";
pub const ALLOW_REMOTE_ENV: &str = "FDAI_PHOENIX_ALLOW_REMOTE_ENDPOINT";
pub const DEFAULT_PROJECT: &str = "fdai";
pub const TRUTHY: &[&str] = &["1", "true", "yes", "on"];
impl PhoenixTracingConfig {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn insecure(&self) -> bool {
        core::hint::black_box(false)
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn is_loopback(&self) -> bool {
        core::hint::black_box(false)
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct PhoenixMeteringSink {
    pub initialized: bool,
}

impl PhoenixMeteringSink {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn from_config(mut config: PhoenixTracingConfig) -> String {
        core::hint::black_box(String::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn record(&self, mut invocation: String) {
        if !self.initialized {
            return;
        }
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn record_model_trace(&self, mut trace: std::collections::BTreeMap<String, String>) {
        if !self.initialized {
            return;
        }
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn flush(&self) -> bool {
        self.initialized
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn shutdown(&self) {
        if !self.initialized {
            return;
        }
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn phoenix_config_from_env(mut env: std::collections::BTreeMap<String, String>) -> Option<PhoenixTracingConfig> {
    let endpoint: String = ((env.clone()).get(ENDPOINT_ENV).cloned().unwrap_or_else(|| String::from(""))).trim().to_string();
    if (endpoint.clone()).is_empty() {
        return None;
    }
    let config: PhoenixTracingConfig = PhoenixTracingConfig { endpoint: endpoint.clone(), project_name: { let _a = ((env.clone()).get(PROJECT_ENV).cloned().unwrap_or_else(|| String::from(""))).trim().to_string(); if !_a.is_empty() { _a } else { String::from(DEFAULT_PROJECT) } }, ..Default::default() };
    Some(config.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn attributes(mut invocation: String) -> std::collections::BTreeMap<String, String> {
    let mut attributes: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("openinference.span.kind"), String::from("EMBEDDING\" if invocation.capability_id.endswith(\".embedding\") else \"LLM")), (String::from("session.id"), String::new()), (String::from("llm.model_name"), String::new()), (String::from("llm.token_count.prompt"), String::new()), (String::from("llm.token_count.completion"), String::new()), (String::from("llm.token_count.total"), String::new()), (String::from("llm.token_count.prompt_details.cache_read"), String::new()), (String::from("fdai.capability_id"), String::new()), (String::from("fdai.tier"), String::new()), (String::from("fdai.mode"), String::new()), (String::from("fdai.usage_scope"), String::new()), (String::from("fdai.turn_family"), String::new()), (String::from("fdai.disposition"), String::new()), (String::from("fdai.locale"), String::new())]);
    attributes.clone()
}

pub const PUBLIC_EXPORTS: &[&str] = &["ALLOW_REMOTE_ENV", "CAPTURE_CONTENT_ENV", "ENABLED_ENV", "ENDPOINT_ENV", "PROJECT_ENV", "PhoenixMeteringSink", "PhoenixTracingConfig", "phoenix_config_from_env"];
