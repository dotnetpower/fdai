pub const MAX_BASELINE_BYTES: i64 = 16777216;
pub const MAX_ID_CHARS: i64 = 4096;
pub const MAX_TEXT_CHARS: i64 = 512;
pub const MAX_ATTRIBUTE_CHARS: i64 = 4096;

#[derive(Clone, Debug, Default, PartialEq)]
pub struct AzureBlobConfigurationBaselineConfig {
    pub blob_url: String,
    pub expected_sha256: String,
    pub request_timeout_seconds: f64,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct AzureBlobConfigurationBaselineSource {
    pub identity: String,
    pub http_client: String,
    pub config: Box<AzureBlobConfigurationBaselineConfig>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct AzureConfigurationObservationConfig {
    pub allowed_scope: String,
    pub subscription_scopes: Vec<String>,
    pub attribute_paths: Vec<String>,
    pub arg_endpoint: String,
    pub arg_api_version: String,
    pub audience: String,
    pub page_size: i64,
    pub max_pages: i64,
    pub max_records: i64,
    pub timeout_seconds: f64,
}

impl AzureConfigurationObservationConfig {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.allowed_scope.trim().is_empty() { return Err("allowed_scope must be non-empty"); }
        if self.arg_endpoint.trim().is_empty() { return Err("arg_endpoint must be non-empty"); }
        if self.arg_api_version.trim().is_empty() { return Err("arg_api_version must be non-empty"); }
        if self.audience.trim().is_empty() { return Err("audience must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct AzureArgConfigurationObservationSource {
    pub identity: String,
    pub http_client: String,
    pub config: Box<AzureConfigurationObservationConfig>,
    pub clock: String,
}

pub const DEFAULT_ARG_ENDPOINT: &str = "https://management.azure.com";
pub const DEFAULT_ARG_API_VERSION: &str = "2022-10-01";
pub const DEFAULT_AUDIENCE: &str = "https://management.azure.com/.default";
pub const STORAGE_AUDIENCE: &str = "https://storage.azure.com/";
pub const STORAGE_API_VERSION: &str = "2025-05-05";
pub const ATTRIBUTE_PATH: &str = "^[A-Za-z][A-Za-z0-9_]*(?:\\.[A-Za-z][A-Za-z0-9_]*)*$";
pub const SHA256: &str = "^[0-9a-f]{64}$";
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct AzureConfigurationObservationError {
    pub message: String,
}

impl AzureConfigurationObservationError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for AzureConfigurationObservationError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for AzureConfigurationObservationError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct AzureConfigurationBaselineError {
    pub message: String,
}

impl AzureConfigurationBaselineError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for AzureConfigurationBaselineError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for AzureConfigurationBaselineError {}

impl AzureBlobConfigurationBaselineSource {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn load(&self) -> Result<String, &'static str> {
        let headers: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("Authorization"), String::new()), (String::from("x-ms-date"), String::new()), (String::from("x-ms-version"), String::from(STORAGE_API_VERSION))]);
        Ok(String::new())
    }
}

impl AzureArgConfigurationObservationSource {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn observe(&self, mut scope: String) -> Result<String, &'static str> {
        if scope.is_empty() {
            return Err("missing_required_input");
        }
        Err("runtime_binding_required")
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn query(mut attribute_paths: Vec<String>) -> String {
    let mut projections: Vec<String> = vec![String::from("id"), String::from("type"), String::from("name"), String::from("location")];
    String::from("Resources | project \" + \", \".join(projections) + \" | order by id asc")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn resource(mut row: std::collections::BTreeMap<String, String>, mut attribute_paths: Vec<String>) -> Result<String, &'static str> {
    let provider_id: String = required_row_text(row.clone(), String::from("id"), MAX_ID_CHARS).unwrap_or_else(|_| String::new());
    let name: String = required_row_text(row.clone(), String::from("name"), MAX_TEXT_CHARS).unwrap_or_else(|_| String::new());
    let resource_type: String = required_row_text(row.clone(), String::from("type"), MAX_TEXT_CHARS).unwrap_or_else(|_| String::new());
    let location: String = location(row.clone()).unwrap_or_else(|_| String::new());
    let mut attributes: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::<String, String>::new();
    let mut unknown: std::collections::BTreeSet<String> = std::collections::BTreeSet::<String>::new();
    Ok(String::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn required_row_text(mut row: std::collections::BTreeMap<String, String>, mut field: String, mut max_chars: i64) -> Result<String, &'static str> {
    let value: Option<String> = (row.clone()).get(field.as_str()).cloned();
    if (!(true)) || ((((value.clone()).unwrap_or_default()).trim().to_string()).is_empty()) {
        return Err("ARG configuration row is missing required field fieldr");
    }
    let normalized: String = ((value.clone()).unwrap_or_default()).trim().to_string();
    if (((normalized.clone()).len() as i64)) > (max_chars) {
        return Err("ARG configuration row field fieldr exceeds max_chars characters");
    }
    Ok(normalized.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn location(mut row: std::collections::BTreeMap<String, String>) -> Result<String, &'static str> {
    let value: Option<String> = (row.clone()).get("location").cloned();
    if !(true) {
        return Err("ARG configuration row is missing required field location");
    }
    let normalized: String = ((value.clone()).unwrap_or_default()).trim().to_string();
    if (((normalized.clone()).len() as i64)) > (MAX_TEXT_CHARS) {
        return Err("ARG configuration row field location exceeds _MAX_TEXT_CHARS characters");
    }
    Ok({ let _a = normalized.clone(); if !_a.is_empty() { _a } else { String::from("global") } })
}

pub const PUBLIC_EXPORTS: &[&str] = &["AzureArgConfigurationObservationSource", "AzureBlobConfigurationBaselineConfig", "AzureBlobConfigurationBaselineSource", "AzureConfigurationBaselineError", "AzureConfigurationObservationConfig", "AzureConfigurationObservationError"];
