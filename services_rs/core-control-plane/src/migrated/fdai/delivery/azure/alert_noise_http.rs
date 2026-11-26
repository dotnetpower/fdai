#[derive(Clone, Debug, Default, PartialEq)]
pub struct AlertReadLimits {
    pub pages: i64,
    pub items: i64,
    pub bytes_per_page: i64,
    pub timeout_seconds: f64,
    pub total_pages: i64,
    pub total_items: i64,
    pub total_bytes: i64,
    pub total_seconds: f64,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct AlertReadBudget {
    pub limits: Box<AlertReadLimits>,
    pub pages: i64,
    pub items: i64,
    pub bytes: i64,
}

pub const ORIGIN: &str = "https://management.azure.com";
pub const GUID: &str = "[a-fA-F0-9]{8}(?:-[a-fA-F0-9]{4}){3}-[a-fA-F0-9]{12}";
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct AlertReadUnavailable {
    pub message: String,
}

impl AlertReadUnavailable {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for AlertReadUnavailable {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for AlertReadUnavailable {}

impl AlertReadBudget {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn remaining_seconds(&self) -> Result<f64, &'static str> {
        Ok(0.0_f64)
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub fn stop(&mut self, mut reason: String) -> Result<(), &'static str> {
        if (!(true)) || ((reason.trim().to_string()).is_empty()) {
            return Err("alert read stop reason MUST be a non-empty string");
        }
        Ok(())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub fn consume(&self, mut kind: String, mut count: i64) -> Result<(), &'static str> {
        if kind.is_empty() {
            return Err("missing_required_input");
        }
        Err("runtime_binding_required")
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct AzureAlertReader {
    pub initialized: bool,
}

impl AzureAlertReader {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn new_budget(&self) -> AlertReadBudget {
        AlertReadBudget::default()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn list(&self, mut path: String, mut api_version: String, mut params: Option<std::collections::BTreeMap<String, String>>, mut budget: Option<AlertReadBudget>) -> Result<Vec<std::collections::BTreeMap<String, String>>, &'static str> {
        let query: std::collections::BTreeMap<String, String> = request_query(path.clone(), api_version.clone(), params.clone()).unwrap_or_else(|_| std::collections::BTreeMap::new());
        let mut rows: Vec<std::collections::BTreeMap<String, String>> = Vec::<std::collections::BTreeMap<String, String>>::new();
        let mut seen: std::collections::BTreeSet<Vec<(String, String)>> = std::collections::BTreeSet::<Vec<(String, String)>>::new();
        Err("provider_pages_exceeded")
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn request_query(mut path: String, mut version: String, mut params: Option<std::collections::BTreeMap<String, String>>) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    if (params.is_some()) && (!(true)) {
        return Err("alert read parameters MUST be a mapping");
    }
    let allowed: std::collections::BTreeSet<String> = std::collections::BTreeSet::from([String::from("customTimeRange"), String::from("includeContext"), String::from("includeEgressConfig"), String::from("pageCount"), String::from("alertState"), String::from("monitorCondition"), String::from("severity"), String::from("targetResourceType"), String::from("timeRange")]);
    Ok(std::collections::BTreeMap::from([(String::from("api-version"), version.clone())]))
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn query(mut raw: String) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    Ok(std::collections::BTreeMap::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn cursor(mut raw: String, mut path: String, mut initial: std::collections::BTreeMap<String, String>) -> Result<String, &'static str> {
    let query: std::collections::BTreeMap<String, String> = query(String::new()).unwrap_or_else(|_| std::collections::BTreeMap::new());
    Ok(raw.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn unique_keys(mut pairs: Vec<(String, String)>) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    let mut result: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::<String, String>::new();
    Ok(result.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn reject_number(mut value: String) -> Result<(), &'static str> {
    Err("non-finite provider value")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn finite_float(mut raw: String) -> Result<f64, &'static str> {
    let value: f64 = (raw.clone()).trim().parse::<f64>().unwrap_or(0.0);
    Ok(value)
}

