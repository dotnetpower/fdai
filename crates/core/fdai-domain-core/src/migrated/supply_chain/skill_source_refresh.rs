pub const BASE_BACKOFF_SECONDS: i64 = 300;
pub const MAX_BACKOFF_SECONDS: i64 = 21600;
pub const CLAIM_SECONDS: i64 = 300;

#[derive(Clone, Debug, Default, PartialEq)]
pub struct SkillSourceRefreshAttempt {
    pub source_id: String,
    pub status: String,
    pub candidate_id: Option<String>,
    pub retry_at: Option<String>,
}

pub trait SkillSourceAdapterFactory {
    fn call(&self, source: String) -> String;
}

pub trait SkillSourceRefresher {
    fn refresh(&self, source: String, adapter: String, fetched_at: String, prior_etag: Option<String>, prior_installed_digest: Option<String>) -> String;
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct SkillSourceRefreshOrchestrator {
    pub initialized: bool,
}

impl SkillSourceRefreshOrchestrator {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn run_due(&self, mut now: String) -> Result<Vec<SkillSourceRefreshAttempt>, &'static str> {
        let mut attempts: Vec<SkillSourceRefreshAttempt> = Vec::<SkillSourceRefreshAttempt>::new();
        Ok(attempts.clone())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn refresh_source(&self, mut source: String, mut state: Option<String>, mut now: String) -> SkillSourceRefreshAttempt {
        SkillSourceRefreshAttempt { status: String::from("not_modified\" if result.not_modified else \"refreshed"), ..Default::default() }
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn backoff(mut error_count: i64) -> String {
    core::hint::black_box(String::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn failed_state(mut previous: String, mut retry_at: String, mut error_kind: String) -> String {
    if previous.is_empty() {
        return String::new();
    }
    String::new()
}

pub const PUBLIC_EXPORTS: &[&str] = &["SkillSourceAdapterFactory", "SkillSourceRefreshAttempt", "SkillSourceRefreshOrchestrator", "SkillSourceRefresher"];
