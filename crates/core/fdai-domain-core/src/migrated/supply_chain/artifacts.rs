pub const MAX_ARTIFACT_BYTES: i64 = 33554432;

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum TrustedArtifactKind {
    #[default]
    Extension,
    Skill,
    SkillBundle,
}

impl TrustedArtifactKind {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Extension => "extension",
            Self::Skill => "skill",
            Self::SkillBundle => "skill_bundle",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum TrustedArtifactState {
    #[default]
    Disabled,
    Enabled,
}

impl TrustedArtifactState {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Disabled => "disabled",
            Self::Enabled => "enabled",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct TrustedArtifactRecord {
    pub kind: TrustedArtifactKind,
    pub artifact_id: String,
    pub version: String,
    pub source: String,
    pub content_sha256: String,
    pub artifact: Vec<u8>,
    pub signature: Vec<u8>,
    pub state: TrustedArtifactState,
    pub revision: i64,
    pub created_at: String,
    pub updated_at: String,
}

impl TrustedArtifactRecord {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.artifact_id.trim().is_empty() { return Err("artifact_id must be non-empty"); }
        if self.version.trim().is_empty() { return Err("version must be non-empty"); }
        if self.source.trim().is_empty() { return Err("source must be non-empty"); }
        if self.content_sha256.trim().is_empty() { return Err("content_sha256 must be non-empty"); }
        if self.created_at.trim().is_empty() { return Err("created_at must be non-empty"); }
        if self.updated_at.trim().is_empty() { return Err("updated_at must be non-empty"); }
        Ok(())
    }
}

pub const ID: &str = "^[a-z][a-z0-9.-]{2,127}$";
pub const VERSION: &str = "^(0|[1-9]\\d*)\\.(0|[1-9]\\d*)\\.(0|[1-9]\\d*)$";
pub const DIGEST: &str = "^[a-f0-9]{64}$";
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct TrustedArtifactConflictError {
    pub message: String,
}

impl TrustedArtifactConflictError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for TrustedArtifactConflictError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for TrustedArtifactConflictError {}

pub trait TrustedArtifactStore {
    fn put(&self, record: TrustedArtifactRecord, expected_revision: i64) -> String;
}

pub const PUBLIC_EXPORTS: &[&str] = &["TrustedArtifactConflictError", "TrustedArtifactKind", "TrustedArtifactRecord", "TrustedArtifactState", "TrustedArtifactStore"];
