pub const MAX_TEXT: i64 = 256;

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum SkillSourceKind {
    #[default]
    GithubRepository,
}

impl SkillSourceKind {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::GithubRepository => "github_repository",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum SkillSourceTrustTier {
    #[default]
    OrganizationApproved,
}

impl SkillSourceTrustTier {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::OrganizationApproved => "organization_approved",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum SkillSourceRefreshPolicy {
    #[default]
    Manual,
    Scheduled,
}

impl SkillSourceRefreshPolicy {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Manual => "manual",
            Self::Scheduled => "scheduled",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct SkillSource {
    pub source_id: String,
    pub kind: SkillSourceKind,
    pub location: String,
    pub trust_tier: SkillSourceTrustTier,
    pub owner: String,
    pub allowed_path: String,
    pub authentication_audience_ref: String,
    pub refresh_policy: SkillSourceRefreshPolicy,
    pub refresh_interval_seconds: i64,
    pub enabled: bool,
}

impl SkillSource {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.source_id.trim().is_empty() { return Err("source_id must be non-empty"); }
        if self.location.trim().is_empty() { return Err("location must be non-empty"); }
        if self.owner.trim().is_empty() { return Err("owner must be non-empty"); }
        if self.allowed_path.trim().is_empty() { return Err("allowed_path must be non-empty"); }
        if self.authentication_audience_ref.trim().is_empty() { return Err("authentication_audience_ref must be non-empty"); }
        Ok(())
    }
}

pub const SOURCE_ID: &str = "^[a-z][a-z0-9.-]{2,127}$";
pub const GITHUB_REPOSITORY: &str = "^[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}$";
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct SkillSourceRegistryError {
    pub message: String,
}

impl SkillSourceRegistryError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for SkillSourceRegistryError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for SkillSourceRegistryError {}

pub trait SkillSourceStore {
    fn put(&self, source: SkillSource, now: String) -> String;
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct SkillSourceRegistry {
    pub initialized: bool,
}

impl SkillSourceRegistry {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn register(&self, mut source: SkillSource) -> Result<String, &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn enable(&self, mut source_id: String) -> String {
        let source: SkillSource = self.get(source_id.clone()).unwrap_or_else(|_| Default::default());
        String::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn disable(&self, mut source_id: String) -> String {
        let source: SkillSource = self.get(source_id.clone()).unwrap_or_else(|_| Default::default());
        String::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn get(&self, mut source_id: String) -> Result<SkillSource, &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn list(&self) -> Vec<SkillSource> {
        if !self.initialized {
            return Vec::new();
        }
        Vec::new()
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn safe_relative_path(mut value: String) -> Result<(), &'static str> {
    Err("runtime_binding_required")
}

pub const PUBLIC_EXPORTS: &[&str] = &["SkillSource", "SkillSourceKind", "SkillSourceRefreshPolicy", "SkillSourceRegistry", "SkillSourceRegistryError", "SkillSourceStore", "SkillSourceTrustTier"];
