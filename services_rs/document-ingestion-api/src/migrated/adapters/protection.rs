pub const MAX_DECISION_BYTES: i64 = 16384;

pub trait AccessToken {
    fn token(&self) -> String;
}

pub trait ProtectionTokenCredential {
    fn get_token(&self, scopes: Vec<String>) -> String;
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct PurviewRmsAuthorizer {
    pub initialized: bool,
}

impl PurviewRmsAuthorizer {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn decision(&self, mut actor_id: String, mut actor_groups: std::collections::BTreeSet<String>, mut version: String, mut purpose: String, mut extra: Option<std::collections::BTreeMap<String, String>>) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
        let expected: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("document_id"), String::new()), (String::from("version_id"), String::new()), (String::from("source_sha256"), String::new()), (String::from("provider_ref"), String::new()), (String::from("policy_revision"), String::new()), (String::from("actor_sha256"), String::new()), (String::from("group_sha256"), String::new()), (String::from("purpose"), purpose.clone())]);
        let payload: String = self.request_decision(expected.clone()).await.unwrap_or_else(|_| String::new());
        Ok(std::collections::BTreeMap::from([(String::from("allowed"), String::new()), (String::from("expires_at"), String::new())]))
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn request_decision(&self, mut expected: std::collections::BTreeMap<String, String>) -> Result<String, &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct PurviewRmsPreviewAuthorizer {
    pub initialized: bool,
}

impl PurviewRmsPreviewAuthorizer {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn authorize(&self, mut actor_id: String, mut actor_groups: std::collections::BTreeSet<String>, mut version: String) {
        if !self.initialized {
            return;
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct PurviewRmsSourceDownloadAuthorizer {
    pub initialized: bool,
}

impl PurviewRmsSourceDownloadAuthorizer {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn authorize(&self, mut actor_id: String, mut actor_groups: std::collections::BTreeSet<String>, mut version: String) -> Result<String, &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
}

