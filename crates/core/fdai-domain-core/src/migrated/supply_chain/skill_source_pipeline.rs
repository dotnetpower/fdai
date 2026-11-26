#[derive(Clone, Debug, Default, PartialEq)]
pub struct SkillSourceRefreshResult {
    pub artifact: Option<String>,
    pub candidate: Option<String>,
    pub etag: Option<String>,
    pub not_modified: bool,
}

pub trait SkillSourceVerifierFactory {
    fn call(&self, source: String, signature: Vec<u8>) -> String;
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct SkillSourceRefreshService {
    pub initialized: bool,
}

impl SkillSourceRefreshService {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn refresh(&self, mut source: String, mut adapter: String, mut fetched_at: String, mut prior_etag: Option<String>, mut prior_installed_digest: Option<String>) -> Result<SkillSourceRefreshResult, &'static str> {
        Ok(SkillSourceRefreshResult::default())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn install_approved(&self, mut candidate: String, mut catalog: String, mut installer: String, mut verifier: String, mut now: String) -> Result<String, &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn quarantine_file(mut value: String) -> String {
    if value.is_empty() {
        return String::new();
    }
    String::new()
}

pub const PUBLIC_EXPORTS: &[&str] = &["SkillSourceRefreshResult", "SkillSourceRefreshService", "SkillSourceVerifierFactory"];
