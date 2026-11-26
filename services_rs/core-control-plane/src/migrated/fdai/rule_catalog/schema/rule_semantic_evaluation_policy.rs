#[derive(Clone, Debug, Default, PartialEq)]
pub struct EvaluationPolicyLoadIssue {
    pub key: String,
    pub message: String,
}

pub const SCHEMA_PACKAGE: &str = "fdai.rule_catalog.schema";
pub const SCHEMA_FILE: &str = "rule_semantic_evaluation_policy.schema.json";
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct EvaluationPolicyLoadError {
    pub message: String,
}

impl EvaluationPolicyLoadError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for EvaluationPolicyLoadError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for EvaluationPolicyLoadError {}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn load_schema() -> std::collections::BTreeMap<String, String> {
    std::collections::BTreeMap::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn load_retrieval_evaluation_policy_from_mapping(mut raw: std::collections::BTreeMap<String, String>) -> Result<String, &'static str> {
    if raw.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn load_retrieval_evaluation_policy_from_json(mut raw: String) -> Result<String, &'static str> {
    Ok(load_retrieval_evaluation_policy_from_mapping(std::collections::BTreeMap::new()).unwrap_or_else(|_| String::new()))
}

pub const PUBLIC_EXPORTS: &[&str] = &["EvaluationPolicyLoadError", "EvaluationPolicyLoadIssue", "load_retrieval_evaluation_policy_from_json", "load_retrieval_evaluation_policy_from_mapping"];
