#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ConfigurationBaselineStatus {
    #[default]
    Candidate,
    Active,
    Superseded,
    Archived,
}

impl ConfigurationBaselineStatus {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Candidate => "candidate",
            Self::Active => "active",
            Self::Superseded => "superseded",
            Self::Archived => "archived",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct RegisteredConfigurationBaseline {
    pub baseline: String,
    pub status: ConfigurationBaselineStatus,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct RegistryConfigurationBaselineSource {
    pub registry: String,
    pub scope: String,
    pub version: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ConfigurationBaselineNotFoundError {
    pub message: String,
}

impl ConfigurationBaselineNotFoundError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for ConfigurationBaselineNotFoundError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for ConfigurationBaselineNotFoundError {}

impl RegisteredConfigurationBaseline {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn key(&self) -> (String, String) {
        (String::new(), String::new())
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ConfigurationBaselineRegistry {
    pub initialized: bool,
}

impl ConfigurationBaselineRegistry {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn list(&self, mut scope: Option<String>) -> Vec<RegisteredConfigurationBaseline> {
        if !self.initialized {
            return Vec::new();
        }
        Vec::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn get(&self, mut scope: String, mut version: String) -> Result<RegisteredConfigurationBaseline, &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn active(&self, mut scope: String) -> Result<RegisteredConfigurationBaseline, &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
}

impl RegistryConfigurationBaselineSource {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn load(&self) -> String {
        core::hint::black_box(String::new())
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["ConfigurationBaselineNotFoundError", "ConfigurationBaselineRegistry", "ConfigurationBaselineStatus", "RegisteredConfigurationBaseline", "RegistryConfigurationBaselineSource"];
