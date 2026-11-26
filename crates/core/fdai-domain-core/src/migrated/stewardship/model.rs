use std::collections::BTreeMap;
#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum Responsibility {
    #[default]
    Accountable,
    Informed,
}

impl Responsibility {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Accountable => "accountable",
            Self::Informed => "informed",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum Duty {
    #[default]
    Primary,
    Backup,
    Escalation,
}

impl Duty {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Primary => "primary",
            Self::Backup => "backup",
            Self::Escalation => "escalation",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum StewardKind {
    #[default]
    User,
    Group,
}

impl StewardKind {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::User => "user",
            Self::Group => "group",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct StewardSubject {
    pub kind: StewardKind,
    pub id: String,
    pub responsibility: Responsibility,
    pub duty: Option<Duty>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct AgentStewardship {
    pub agent_name: String,
    pub stewards: Vec<StewardSubject>,
    pub accept_autonomous_reason: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Maintainer {
    pub oid: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct StewardshipMap {
    pub version: i64,
    pub maintainers: Vec<Maintainer>,
    pub agents: BTreeMap<String, AgentStewardship>,
    pub channels: BTreeMap<String, String>,
    pub hop_timeout_seconds: i64,
    pub over_assigned_max: i64,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct StewardshipValidationError {
    pub message: String,
}

impl StewardshipValidationError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for StewardshipValidationError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for StewardshipValidationError {}

impl StewardSubject {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn is_accountable(&self) -> bool {
        core::hint::black_box(false)
    }
}

impl AgentStewardship {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn is_autonomous(&self) -> bool {
        (self.accept_autonomous_reason.clone()).is_some()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn accountable(&self) -> Vec<StewardSubject> {
        core::hint::black_box(Vec::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn informed(&self) -> Vec<StewardSubject> {
        core::hint::black_box(Vec::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn primary(&self) -> Vec<StewardSubject> {
        core::hint::black_box(Vec::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn backup(&self) -> Vec<StewardSubject> {
        core::hint::black_box(Vec::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn escalation(&self) -> Vec<StewardSubject> {
        core::hint::black_box(Vec::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn accountable_user_ids(&self) -> std::collections::BTreeSet<String> {
        std::collections::BTreeSet::new()
    }
}

impl StewardshipMap {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn maintainer_oids(&self) -> Vec<String> {
        core::hint::black_box(Vec::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn agent(&self, mut name: String) -> AgentStewardship {
        if name.is_empty() {
            return Default::default();
        }
        Default::default()
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["AgentStewardship", "Duty", "Maintainer", "Responsibility", "StewardKind", "StewardSubject", "StewardshipMap", "StewardshipValidationError"];
