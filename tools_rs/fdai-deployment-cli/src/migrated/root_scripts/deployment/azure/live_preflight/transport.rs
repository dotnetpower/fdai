pub const DEFAULT_OVERALL_DEADLINE_SECONDS: i64 = 300;

pub const ARM_ENDPOINT: &str = "https://management.azure.com";
pub const ARM_AUDIENCE: &str = "https://management.azure.com";
pub const VAULT_AUDIENCE: &str = "https://vault.azure.net";
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct PreflightError {
    pub message: String,
}

impl PreflightError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for PreflightError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for PreflightError {}

pub trait AzureReader {
    fn get_json(&self, path: String, api_version: String) -> String;
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct AzureCliReader {
    pub initialized: bool,
}

impl AzureCliReader {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn remaining_seconds(&self) -> f64 {
        0.0_f64
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub fn get_json(&self, mut path: String, mut api_version: String) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
        Ok(std::collections::BTreeMap::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub fn get_values(&self, mut path: String, mut api_version: String, mut params: Option<std::collections::BTreeMap<String, String>>) -> Result<Vec<std::collections::BTreeMap<String, String>>, &'static str> {
        let query: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("api-version"), api_version.clone())]);
        let mut values: Vec<std::collections::BTreeMap<String, String>> = Vec::<std::collections::BTreeMap<String, String>>::new();
        let mut pages: i64 = 0_i64;
        Ok(values.clone())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub fn query_role_assignments(&self, mut subscription_id: String, mut principal_id: String) -> Result<Vec<std::collections::BTreeMap<String, String>>, &'static str> {
        let query: String = String::from("AuthorizationResources \" \"| where type =~ 'microsoft.authorization/roleassignments' \" f\"| where tostring(properties.principalId) =~ '{principal_id}' \" \"| project roleDefinitionId=tostring(properties.roleDefinitionId), \" \"scope=tostring(properties.scope)");
        let body: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("subscriptions"), String::new()), (String::from("query"), query.clone()), (String::from("options"), String::new())]);
        let url: String = format!("{}/providers/Microsoft.ResourceGraph/resources?api-version=2022-10-01", String::from(ARM_ENDPOINT));
        Ok(Vec::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn secret_status(&self, mut vault_endpoint: String, mut secret_name: String) -> i64 {
        0_i64
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub fn request_json(&self, mut url: String, mut audience: String, mut method: String, mut body: Option<std::collections::BTreeMap<String, String>>) -> Result<(i64, String), &'static str> {
        Err("Azure read exhausted its bounded retry budget")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn token(&self, mut audience: String) -> Result<String, &'static str> {
        let remaining: f64 = self.remaining_seconds();
        if (remaining) <= (0.0) {
            return Err("Azure reads exceeded the bounded  fself._overall_deadline_seconds:gs pre");
        }
        Ok(String::new())
    }
}

