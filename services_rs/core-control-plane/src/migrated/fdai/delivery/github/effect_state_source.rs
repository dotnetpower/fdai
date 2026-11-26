#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum GitHubArtifactKind {
    #[default]
    PullRequest,
    Issue,
}

impl GitHubArtifactKind {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::PullRequest => "pull_request",
            Self::Issue => "issue",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct GitHubArtifactReading {
    pub exists: bool,
    pub state: Option<String>,
    pub head_sha: Option<String>,
    pub merged: Option<bool>,
    pub auto_merge_enabled: bool,
    pub labels: Vec<String>,
    pub observed_at: String,
    pub recorded_at: String,
    pub censoring_refs: Vec<String>,
    pub conflicts: Vec<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct GitHubArtifactEffectSourceConfig {
    pub owner: String,
    pub repo: String,
    pub kind: GitHubArtifactKind,
    pub number: i64,
    pub source_instance_id: String,
    pub expected_head_sha: Option<String>,
    pub require_manual_merge: bool,
    pub required_label: Option<String>,
}

impl GitHubArtifactEffectSourceConfig {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.owner.trim().is_empty() { return Err("owner must be non-empty"); }
        if self.repo.trim().is_empty() { return Err("repo must be non-empty"); }
        if self.source_instance_id.trim().is_empty() { return Err("source_instance_id must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct GitHubArtifactReadError {
    pub message: String,
}

impl GitHubArtifactReadError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for GitHubArtifactReadError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for GitHubArtifactReadError {}

pub trait GitHubArtifactReader {
    fn read_artifact(&self, owner: String, repo: String, kind: GitHubArtifactKind, number: i64) -> GitHubArtifactReading;
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct GitHubArtifactEffectSource {
    pub initialized: bool,
}

impl GitHubArtifactEffectSource {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn source_instance_id(&self) -> String {
        if !self.initialized {
            return String::new();
        }
        String::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn read(&self, mut binding: String) -> String {
        state_from(Default::default(), Default::default())
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn state_from(mut reading: GitHubArtifactReading, mut config: GitHubArtifactEffectSourceConfig) -> String {
    core::hint::black_box(String::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
#[allow(clippy::type_complexity)]
pub fn expected_state(mut reading: GitHubArtifactReading, mut config: GitHubArtifactEffectSourceConfig) -> (Option<bool>, String) {
    if (config.require_manual_merge) && (reading.auto_merge_enabled) {
        return (Some(false), format!("pull request {} enabled auto-merge on a manual-merge path", config.number));
    }
    (None, String::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn reading_from_payload(mut payload: std::collections::BTreeMap<String, String>, mut kind: GitHubArtifactKind, mut observed_at: String) -> Result<GitHubArtifactReading, &'static str> {
    let state: Option<String> = (payload.clone()).get("state").cloned();
    let updated_raw: Option<String> = (payload.clone()).get("updated_at").cloned();
    let head: Option<String> = (payload.clone()).get("head").cloned();
    let merged: Option<String> = (payload.clone()).get("merged").cloned();
    let labels: Option<String> = (payload.clone()).get("labels").cloned();
    Ok(GitHubArtifactReading { exists: true, state: state.clone(), auto_merge_enabled: ((payload.clone()).get("auto_merge").cloned()).is_some(), ..Default::default() })
}

pub const PUBLIC_EXPORTS: &[&str] = &["GitHubArtifactEffectSource", "GitHubArtifactEffectSourceConfig", "GitHubArtifactKind", "GitHubArtifactReadError", "GitHubArtifactReader", "GitHubArtifactReading", "reading_from_payload"];
