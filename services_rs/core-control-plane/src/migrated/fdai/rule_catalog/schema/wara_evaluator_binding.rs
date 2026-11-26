#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum WaraEvaluatorSemantics {
    #[default]
    MatchingRowsFailed,
}

impl WaraEvaluatorSemantics {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::MatchingRowsFailed => "matching_rows_failed",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct WaraObservationRequirement {
    pub path: String,
    pub value_type: String,
    pub allowed_values: Vec<String>,
    pub expected_boolean: Option<bool>,
    pub minimum_items: i64,
    pub maximum_items: Option<i64>,
    pub allowed_items: Vec<String>,
    pub unique_items: bool,
    pub minimum_length: i64,
    pub forbidden_keys: Vec<String>,
    pub required_keys: Vec<String>,
    pub allow_null: bool,
}

impl WaraObservationRequirement {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.value_type.as_str(), "string" | "boolean" | "number" | "array" | "object") { return Err("invalid value_type literal"); }
        if !(0_i64..=10000_i64).contains(&self.minimum_items) { return Err("minimum_items out of bounds"); }
        if !(0_i64..=4096_i64).contains(&self.minimum_length) { return Err("minimum_length out of bounds"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct WaraEvaluatorBinding {
    pub aprl_guid: String,
    pub query_digest: String,
    pub evaluator_ref: String,
    pub provider: String,
    pub semantics: WaraEvaluatorSemantics,
    pub resource_id_column: String,
    pub reviewer: String,
    pub review_state: String,
    pub observation_requirements: Vec<WaraObservationRequirement>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct WaraEvaluatorBindingCatalog {
    pub schema_version: String,
    pub source_revision: String,
    pub crosswalk_digest: String,
    pub bindings: Vec<WaraEvaluatorBinding>,
    pub overlay_digest: String,
}

pub const SHA256: &str = "^sha256:[a-f0-9]{64}$";
pub const GIT_REF: &str = "^[a-f0-9]{40}$";
pub const IDENTIFIER: &str = "^[a-z0-9][a-z0-9._:-]{0,255}$";
impl WaraObservationRequirement {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn validate_constraints(&self) -> Result<WaraObservationRequirement, &'static str> {
        if (!(self.allowed_values.clone()).is_empty()) && ((self.value_type.clone()) != (String::from("string"))) {
            return Err("WARA allowed values require a string observation");
        }
        if (self.expected_boolean.is_some()) && ((self.value_type.clone()) != (String::from("boolean"))) {
            return Err("WARA expected boolean requires a boolean observation");
        }
        if (((self.minimum_items) != 0) || ((self.maximum_items.is_some()) || ((!(self.allowed_items.clone()).is_empty()) || (self.unique_items)))) && ((self.value_type.clone()) != (String::from("array"))) {
            return Err("WARA item constraints require an array observation");
        }
        if ((self.minimum_length) != 0) && ((self.value_type.clone()) != (String::from("string"))) {
            return Err("WARA minimum length requires a string observation");
        }
        if ((!(self.forbidden_keys.clone()).is_empty()) || (!(self.required_keys.clone()).is_empty())) && ((self.value_type.clone()) != (String::from("object"))) {
            return Err("WARA key constraints require an object observation");
        }
        Ok(self.clone())
    }
}

impl WaraEvaluatorBinding {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn key(&self) -> (String, String) {
        (self.aprl_guid.clone(), self.query_digest.clone())
    }
}

impl WaraEvaluatorBindingCatalog {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn validate_identity(&self) -> Result<WaraEvaluatorBindingCatalog, &'static str> {
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn resolve(&self, mut aprl_guid: String, mut query_digest: String) -> Option<WaraEvaluatorBinding> {
        if aprl_guid.is_empty() {
            return None;
        }
        None
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn load_wara_evaluator_bindings(mut path: String, mut catalog: String, mut queries: String) -> Result<WaraEvaluatorBindingCatalog, &'static str> {
    if path.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

pub const PUBLIC_EXPORTS: &[&str] = &["WaraEvaluatorBinding", "WaraEvaluatorBindingCatalog", "WaraEvaluatorSemantics", "WaraObservationRequirement", "load_wara_evaluator_bindings"];
