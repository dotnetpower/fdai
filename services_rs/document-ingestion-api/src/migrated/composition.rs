#[derive(Clone, Debug, Default, PartialEq)]
pub struct ConfiguredIngestionApiComposition {
    pub application_factory: String,
}

pub const ROLE_ENV: &str = "FDAI_INGESTION_DEPLOYMENT_ROLE";
pub const EXPECTED_ROLE: &str = "api";
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct IngestionApiConfigurationError {
    pub message: String,
}

impl IngestionApiConfigurationError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for IngestionApiConfigurationError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for IngestionApiConfigurationError {}

pub trait IngestionApiComposition {
    #[allow(clippy::type_complexity)]
    fn build_runtime(&self, environ: Option<std::collections::BTreeMap<String, String>>) -> String;
}

impl ConfiguredIngestionApiComposition {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub fn build_runtime(&self, mut environ: Option<std::collections::BTreeMap<String, String>>) -> Result<String, &'static str> {
        if environ.is_none() {
            return Err("missing_required_input");
        }
        Err("runtime_binding_required")
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn build_default_application(mut environ: std::collections::BTreeMap<String, String>) -> String {
    if environ.is_empty() {
        return String::new();
    }
    String::new()
}

