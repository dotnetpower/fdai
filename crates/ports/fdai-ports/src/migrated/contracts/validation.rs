#[derive(Clone, Debug, Default, PartialEq)]
pub struct ValidationIssue {
    pub path: String,
    pub message: String,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ContractValidationError {
    pub message: String,
}

impl ContractValidationError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for ContractValidationError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for ContractValidationError {}

pub trait ContractValidator {
    fn py_validate(&self, schema_name: String, instance: std::collections::BTreeMap<String, String>, version: Option<String>);
}

pub trait EventValidator {
    fn py_validate(&self, instance: std::collections::BTreeMap<String, String>) -> String;
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct JsonSchemaContractValidator {
    pub initialized: bool,
}

impl JsonSchemaContractValidator {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub fn py_validate(&self, mut schema_name: String, mut instance: std::collections::BTreeMap<String, String>, mut version: Option<String>) -> Result<(), &'static str> {
        let declared_version: Option<String> = (instance.clone()).get("schema_version").cloned();
        if ((instance.clone()).contains_key("schema_version")) && ((!(true)) || (!((declared_version.clone()).is_some()))) {
            return Err("schema_name ValidationIssuepathschema_version messageversion MUST be non");
        }
        if (version.is_some()) && ((declared_version.is_some()) && ((version.clone()) != Some((declared_version.clone()).unwrap_or_default()))) {
            return Err("schema_name ValidationIssuepathschema_version messageversion differs fro");
        }
        let selected_version: String = if version.is_some() { (version.clone()).unwrap_or_default() } else { (declared_version.clone()).unwrap_or_default() };
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct JsonSchemaEventValidator {
    pub initialized: bool,
}

impl JsonSchemaEventValidator {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn py_validate(&self, mut instance: std::collections::BTreeMap<String, String>) {
        if !self.initialized {
            return;
        }
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn issue(mut err: String) -> ValidationIssue {
    ValidationIssue::default()
}

pub const PUBLIC_EXPORTS: &[&str] = &["ContractValidationError", "ContractValidator", "EventValidator", "JsonSchemaContractValidator", "JsonSchemaEventValidator", "ValidationIssue"];
