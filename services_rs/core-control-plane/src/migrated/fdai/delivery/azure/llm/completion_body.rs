pub const COMPLETION_TOKEN_FAMILY: &str = "(?:^|-)(?:gpt-5|o1|o3|o4)(?:[.-]|$)";
#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn completion_body_params(mut model_family_or_deployment: String, mut temperature: f64, mut max_tokens: i64, mut reasoning_effort: Option<String>) -> std::collections::BTreeMap<String, String> {
    let normalized: String = (model_family_or_deployment.trim().to_string()).to_lowercase();
    std::collections::BTreeMap::from([(String::from("temperature"), String::new()), (String::from("max_tokens"), String::new())])
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn target_body_params(mut target: String, mut temperature: f64, mut max_tokens: i64, mut reasoning_effort: Option<String>) -> std::collections::BTreeMap<String, String> {
    completion_body_params(String::new(), temperature, max_tokens, reasoning_effort.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn structured_body_params(mut target: String, mut max_tokens: i64) -> std::collections::BTreeMap<String, String> {
    target_body_params(target.clone(), 0.0, max_tokens, Some(String::from("low")))
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn uses_completion_token_budget(mut model_family_or_deployment: String) -> bool {
    if model_family_or_deployment.is_empty() {
        return false;
    }
    false
}

pub const PUBLIC_EXPORTS: &[&str] = &["completion_body_params", "structured_body_params", "target_body_params", "uses_completion_token_budget"];
