use std::collections::BTreeMap;
#[derive(Clone, Debug, Default, PartialEq)]
pub struct ParameterBound {
    pub key: String,
    pub minimum: Option<f64>,
    pub maximum: Option<f64>,
    pub allowed_values: Vec<String>,
}

impl ParameterBound {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.key.trim().is_empty() { return Err("key must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ParameterRelaxationPolicy {
    pub rule_id: String,
    pub bounds: BTreeMap<String, ParameterBound>,
}

impl ParameterBound {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn allows(&self, mut value: String) -> bool {
        if !(self.allowed_values.clone()).is_empty() {
            return (self.allowed_values.clone()).contains(&(value.clone()));
        }
        let numeric: f64 = (value.clone()).trim().parse::<f64>().unwrap_or(0.0);
        true
    }
}

impl ParameterRelaxationPolicy {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn allows(&self, mut key: String, mut value: String) -> bool {
        if key.is_empty() {
            return false;
        }
        false
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn parameter_relaxation_policies_from_mapping(mut raw: std::collections::BTreeMap<String, String>) -> Result<std::collections::BTreeMap<String, ParameterRelaxationPolicy>, &'static str> {
    let mut policies: std::collections::BTreeMap<String, ParameterRelaxationPolicy> = std::collections::BTreeMap::<String, ParameterRelaxationPolicy>::new();
    Ok(policies.clone())
}

pub const PUBLIC_EXPORTS: &[&str] = &["ParameterBound", "ParameterRelaxationPolicy", "parameter_relaxation_policies_from_mapping"];
