#[derive(Clone, Debug, Default, PartialEq)]
pub struct SkillSourceRevision {
    pub revision: Option<String>,
    pub etag: Option<String>,
    pub not_modified: bool,
}

impl SkillSourceRevision {
    pub fn validate(&self) -> Result<(), &'static str> {
        Err("runtime_binding_required")
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct SkillSourceFile {
    pub path: String,
    pub content: Vec<u8>,
    pub media_type: String,
    pub is_symlink: bool,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct SkillSourceRateLimitError {
    pub message: String,
}

impl SkillSourceRateLimitError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for SkillSourceRateLimitError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for SkillSourceRateLimitError {}

pub trait SkillSourceAdapter {
    fn resolve_revision(&self, repository: String, prior_etag: Option<String>) -> String;
}

pub const PUBLIC_EXPORTS: &[&str] = &["SkillSourceAdapter", "SkillSourceFile", "SkillSourceRateLimitError", "SkillSourceRevision"];
