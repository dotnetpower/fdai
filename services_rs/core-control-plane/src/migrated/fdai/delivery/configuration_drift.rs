pub const MAX_BASELINE_BYTES: i64 = 16777216;

#[derive(Clone, Debug, Default, PartialEq)]
pub struct JsonFileConfigurationBaselineSource {
    pub path: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct JsonFileConfigurationObservationSource {
    pub path: String,
    pub allowed_scope: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ConfigurationDriftToolProvider {
    pub service: String,
}

pub const PROVIDER_ID: &str = "ConfigurationDriftProvider";
pub const TOOL_ID: &str = "configuration.drift.check";
impl JsonFileConfigurationBaselineSource {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn load(&self) -> String {
        core::hint::black_box(String::new())
    }
}

impl JsonFileConfigurationObservationSource {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn observe(&self, mut scope: String) -> Result<String, &'static str> {
        if (scope.clone()) != (self.allowed_scope.clone()) {
            return Err("requested scope is outside the configured observation source");
        }
        Ok(String::new())
    }
}

impl ConfigurationDriftToolProvider {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn call(&self, mut artifact: String, mut arguments: std::collections::BTreeMap<String, String>) -> Result<String, &'static str> {
        if !(arguments.clone()).is_empty() {
            return Err("configuration drift check accepts no caller arguments");
        }
        Ok(String::new())
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn build_configuration_drift_bundle(mut service: String) -> String {
    if service.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn read_json(mut path: String) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    Ok(std::collections::BTreeMap::new())
}

pub const PUBLIC_EXPORTS: &[&str] = &["ConfigurationDriftToolProvider", "JsonFileConfigurationBaselineSource", "JsonFileConfigurationObservationSource", "build_configuration_drift_bundle"];
