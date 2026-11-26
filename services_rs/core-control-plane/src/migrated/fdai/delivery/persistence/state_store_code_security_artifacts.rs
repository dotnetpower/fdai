pub const MAX_ARTIFACT_BYTES: i64 = 900000;

pub const CODE_SECURITY_ARTIFACT_STATE_PREFIX: &str = "runtime:code-security-issues:";
pub const ALIAS: &str = "^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$";
pub const REVISION: &str = "^[0-9a-f]{40}([0-9a-f]{24})?$";
pub const DIGEST: &str = "^[0-9a-f]{64}$";
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct CodeSecurityArtifactConflictError {
    pub message: String,
}

impl CodeSecurityArtifactConflictError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for CodeSecurityArtifactConflictError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for CodeSecurityArtifactConflictError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct CodeSecurityArtifactTooLargeError {
    pub message: String,
}

impl CodeSecurityArtifactTooLargeError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for CodeSecurityArtifactTooLargeError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for CodeSecurityArtifactTooLargeError {}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn code_security_artifact_state_key(mut repository_alias: String, mut revision: String) -> Result<String, &'static str> {
    Ok(format!("{}{}:{}:artifacts-1.4", String::from(CODE_SECURITY_ARTIFACT_STATE_PREFIX), repository_alias.clone(), revision.clone()))
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn validate_code_security_artifacts(mut raw: std::collections::BTreeMap<String, String>) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    let html: Option<String> = (raw.clone()).get("html").cloned();
    let sarif: Option<String> = (raw.clone()).get("sarif").cloned();
    if (!(true)) || (!(((html.clone()).unwrap_or_default()).starts_with("<!doctype html>"))) {
        return Err("code-security HTML artifact is invalid");
    }
    if !(true) {
        return Err("code-security SARIF artifact is invalid");
    }
    Ok(std::collections::BTreeMap::from([(String::from("html"), (html.clone()).unwrap_or_default()), (String::from("sarif"), (sarif.clone()).unwrap_or_default())]))
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub async fn record_code_security_artifacts(mut store: String, mut repository_alias: String, mut revision: String, mut review_digest: String, mut artifacts: std::collections::BTreeMap<String, String>, mut recorded_at: Option<String>) -> Result<bool, &'static str> {
    let validated: std::collections::BTreeMap<String, String> = validate_code_security_artifacts(artifacts.clone()).unwrap_or_else(|_| std::collections::BTreeMap::new());
    let key: String = code_security_artifact_state_key(repository_alias.clone(), revision.clone()).unwrap_or_else(|_| String::new());
    let row: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("kind"), String::from("code-security-review-artifacts")), (String::from("schema_version"), String::from("1.4.0")), (String::from("repository_alias"), repository_alias.clone()), (String::from("revision"), revision.clone()), (String::from("review_digest"), review_digest.clone()), (String::from("recorded_at"), String::new())]);
    Ok(false)
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub async fn record_code_security_artifact_gap(mut store: String, mut repository_alias: String, mut revision: String, mut review_digest: String, mut reason_code: String, mut recorded_at: Option<String>) -> Result<bool, &'static str> {
    let key: String = code_security_artifact_state_key(repository_alias.clone(), revision.clone()).unwrap_or_else(|_| String::new());
    let row: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("kind"), String::from("code-security-review-artifacts-unavailable")), (String::from("schema_version"), String::from("1.4.0")), (String::from("repository_alias"), repository_alias.clone()), (String::from("revision"), revision.clone()), (String::from("review_digest"), review_digest.clone()), (String::from("recorded_at"), String::new()), (String::from("reason_code"), reason_code.clone())]);
    Ok(false)
}

pub const PUBLIC_EXPORTS: &[&str] = &["CODE_SECURITY_ARTIFACT_STATE_PREFIX", "CodeSecurityArtifactConflictError", "CodeSecurityArtifactTooLargeError", "code_security_artifact_state_key", "record_code_security_artifacts", "record_code_security_artifact_gap", "validate_code_security_artifacts"];
