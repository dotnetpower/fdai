#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn credential_values(mut environment: std::collections::BTreeMap<String, String>) -> Result<(String, std::collections::BTreeMap<String, String>, Vec<String>), &'static str> {
    let static_token: String = ((environment.clone()).get("FDAI_GITOPS_TOKEN").cloned().unwrap_or_else(|| String::from(""))).trim().to_string();
    Ok((String::new(), std::collections::BTreeMap::new(), Vec::new()))
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn github_credentials_configured(mut environment: std::collections::BTreeMap<String, String>) -> bool {
    if environment.is_empty() {
        return false;
    }
    false
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn build_github_token_provider(mut environment: std::collections::BTreeMap<String, String>, mut http_client: String, mut repository: String, mut permissions: Option<Vec<(String, String)>>) -> Result<Option<String>, &'static str> {
    if environment.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

pub const PUBLIC_EXPORTS: &[&str] = &["build_github_token_provider", "github_credentials_configured"];
