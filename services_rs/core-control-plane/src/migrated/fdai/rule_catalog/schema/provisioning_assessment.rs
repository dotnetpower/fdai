#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ProvisioningState {
    #[default]
    Resolved,
    CapacityReduced,
    HilOnly,
    Missing,
}

impl ProvisioningState {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Resolved => "resolved",
            Self::CapacityReduced => "capacity-reduced",
            Self::HilOnly => "hil-only",
            Self::Missing => "missing",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum CapabilityTier {
    #[default]
    Core,
    Quorum,
    Optional,
}

impl CapabilityTier {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Core => "core",
            Self::Quorum => "quorum",
            Self::Optional => "optional",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ProvisioningSeverity {
    #[default]
    Ok,
    Degraded,
    Critical,
}

impl ProvisioningSeverity {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Ok => "ok",
            Self::Degraded => "degraded",
            Self::Critical => "critical",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CapabilityAssessment {
    pub name: String,
    pub tier: CapabilityTier,
    pub state: ProvisioningState,
    pub impact: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ProvisioningReport {
    pub severity: ProvisioningSeverity,
    pub quorum_ok: bool,
    pub capabilities: Vec<CapabilityAssessment>,
    pub reasons: Vec<String>,
}

pub const CORE_REQUIRED: &[&str] = &["t1.embedding", "t1.judge", "t2.reasoner.primary"];
pub const QUORUM_REQUIRED: &[&str] = &["t2.reasoner.secondary"];
impl CapabilityAssessment {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn is_available(&self) -> bool {
        core::hint::black_box(false)
    }
}

impl ProvisioningReport {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn is_complete(&self) -> bool {
        core::hint::black_box(false)
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn degraded(&self) -> Vec<CapabilityAssessment> {
        core::hint::black_box(Vec::new())
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn tier_of(mut name: String) -> CapabilityTier {
    if name.is_empty() {
        return Default::default();
    }
    Default::default()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn state_of(mut status: String) -> ProvisioningState {
    if status.is_empty() {
        return Default::default();
    }
    Default::default()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn assess_provisioning(mut registry: String, mut resolved: String) -> ProvisioningReport {
    let mut assessments: Vec<CapabilityAssessment> = Vec::<CapabilityAssessment>::new();
    let mut reasons: Vec<String> = Vec::<String>::new();
    let mut critical: bool = false;
    ProvisioningReport { capabilities: assessments.clone(), reasons: reasons.clone(), ..Default::default() }
}

pub const PUBLIC_EXPORTS: &[&str] = &["CapabilityAssessment", "CapabilityTier", "ProvisioningReport", "ProvisioningSeverity", "ProvisioningState", "assess_provisioning"];
