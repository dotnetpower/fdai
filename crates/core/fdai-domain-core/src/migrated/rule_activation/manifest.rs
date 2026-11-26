#[derive(Clone, Debug, Default, PartialEq)]
pub struct RuleActivationManifestVerifier {
    pub trust: String,
    pub store: String,
}

pub const PREFIX: &str = "rule-activation:manifest-nonce:";
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct RuleActivationManifestReplayError {
    pub message: String,
}

impl RuleActivationManifestReplayError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for RuleActivationManifestReplayError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for RuleActivationManifestReplayError {}

impl RuleActivationManifestVerifier {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn verify_and_reserve(&self, mut envelope: String, mut now: String, mut expected: String, mut consumed_nonces: Vec<String>) -> Result<String, &'static str> {
        let record: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("schema_version"), String::from("1.0.0")), (String::from("manifest_digest"), String::new()), (String::from("nonce"), String::new()), (String::from("release_id"), String::new()), (String::from("source"), String::new()), (String::from("deployment_scope_digest"), String::new()), (String::from("target_generation_id"), String::new()), (String::from("target_generation_digest"), String::new()), (String::from("profile_id"), String::new()), (String::from("profile_version"), String::new()), (String::from("catalog_manifest_digest"), String::new()), (String::from("revision_registry_root"), String::new()), (String::from("members"), String::new()), (String::from("approval_authority"), String::new()), (String::from("activation_authority"), String::new()), (String::from("execution_authority"), String::new())]);
        Err("Rule activation manifest nonce is bound to different content")
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["RuleActivationManifestReplayError", "RuleActivationManifestVerifier"];
