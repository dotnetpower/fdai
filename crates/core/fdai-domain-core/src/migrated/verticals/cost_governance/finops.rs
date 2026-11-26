#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum FinOpsEnvironment {
    #[default]
    Prod,
    Staging,
    Dev,
}

impl FinOpsEnvironment {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Prod => "prod",
            Self::Staging => "staging",
            Self::Dev => "dev",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum FinOpsActionKind {
    #[default]
    Shutdown,
    RightSize,
    SpotAdopt,
    AutoscaleAdjust,
}

impl FinOpsActionKind {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Shutdown => "shutdown",
            Self::RightSize => "right_size",
            Self::SpotAdopt => "spot_adopt",
            Self::AutoscaleAdjust => "autoscale_adjust",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum FinOpsGuardOutcome {
    #[default]
    Allowed,
    Rejected,
}

impl FinOpsGuardOutcome {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Allowed => "allowed",
            Self::Rejected => "rejected",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ResourceContext {
    pub resource_id: String,
    pub environment: FinOpsEnvironment,
    pub tags: Vec<String>,
    pub current_capacity: i64,
    pub dependent_ids: Vec<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct FinOpsCandidate {
    pub action_id: String,
    pub kind: FinOpsActionKind,
    pub resource: Box<ResourceContext>,
    pub target_capacity: Option<i64>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct FinOpsGuardConfig {
    pub exclusion_tag: String,
    pub production_environments: Vec<FinOpsEnvironment>,
    pub min_capacity_floor: i64,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct FinOpsGuardDecision {
    pub action_id: String,
    pub outcome: FinOpsGuardOutcome,
    pub reasons: Vec<String>,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct FinOpsGuard {
    pub initialized: bool,
}

impl FinOpsGuard {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn evaluate(&self, mut candidate: FinOpsCandidate) -> FinOpsGuardDecision {
        let mut reasons: Vec<String> = Vec::<String>::new();
        FinOpsGuardDecision { action_id: candidate.action_id.clone(), reasons: reasons.clone(), ..Default::default() }
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn evaluate_all(&self, mut candidates: Vec<FinOpsCandidate>) -> Vec<FinOpsGuardDecision> {
        if !self.initialized {
            return Vec::new();
        }
        Vec::new()
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["FinOpsActionKind", "FinOpsCandidate", "FinOpsEnvironment", "FinOpsGuard", "FinOpsGuardConfig", "FinOpsGuardDecision", "FinOpsGuardOutcome", "ResourceContext"];
