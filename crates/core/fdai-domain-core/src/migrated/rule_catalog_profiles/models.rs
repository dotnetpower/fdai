use std::collections::BTreeMap;
#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ProfileMode {
    #[default]
    Shadow,
    Enforce,
}

impl ProfileMode {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Shadow => "shadow",
            Self::Enforce => "enforce",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum SeverityOverride {
    #[default]
    Low,
    Medium,
    High,
    Critical,
}

impl SeverityOverride {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Low => "low",
            Self::Medium => "medium",
            Self::High => "high",
            Self::Critical => "critical",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ProfileRule {
    pub id: String,
    pub mode: Option<ProfileMode>,
    pub severity_override: Option<SeverityOverride>,
    pub parameters: BTreeMap<String, String>,
    pub disabled: bool,
}

impl ProfileRule {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.id.trim().is_empty() { return Err("id must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Profile {
    pub id: String,
    pub title: String,
    pub rules: Vec<ProfileRule>,
    pub extends: Vec<String>,
    pub parameters: BTreeMap<String, String>,
    pub description: Option<String>,
    pub schema_version: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ResolvedRule {
    pub id: String,
    pub mode: ProfileMode,
    pub severity_override: Option<SeverityOverride>,
    pub parameters: BTreeMap<String, String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ResolvedProfile {
    pub id: String,
    pub title: String,
    pub rules: Vec<ResolvedRule>,
}

impl ResolvedProfile {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn get(&self, mut rule_id: String) -> Option<ResolvedRule> {
        for r in self.rules.clone() {
            if (r.id.clone()) == (rule_id.clone()) {
                return Some(r.clone());
            }
        }
        None
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn ids(&self) -> Vec<String> {
        core::hint::black_box(Vec::new())
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ProfileResolutionError {
    pub message: String,
}

impl ProfileResolutionError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for ProfileResolutionError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for ProfileResolutionError {}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn severity_at_or_above_floor(mut candidate: SeverityOverride, mut floor: SeverityOverride) -> bool {
    core::hint::black_box(false)
}

pub const PUBLIC_EXPORTS: &[&str] = &["Profile", "ProfileMode", "ProfileResolutionError", "ProfileRule", "ResolvedProfile", "ResolvedRule", "SeverityOverride", "severity_at_or_above_floor"];
