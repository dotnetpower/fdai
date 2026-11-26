#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct SkillCatalogError {
    pub message: String,
}

impl SkillCatalogError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for SkillCatalogError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for SkillCatalogError {}

pub const PUBLIC_EXPORTS: &[&str] = &["SkillCatalogError"];
