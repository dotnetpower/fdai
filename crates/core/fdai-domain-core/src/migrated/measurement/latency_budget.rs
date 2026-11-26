#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum Tier {
    #[default]
    T0,
    T1,
    T2,
}

impl Tier {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::T0 => "T0",
            Self::T1 => "T1",
            Self::T2 => "T2",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum LatencyOutcome {
    #[default]
    Pass,
    OverBudget,
    Unavailable,
}

impl LatencyOutcome {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Pass => "pass",
            Self::OverBudget => "over_budget",
            Self::Unavailable => "unavailable",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct LatencyObservation {
    pub tier: Tier,
    pub p95_ms: Option<f64>,
    pub sample_size: i64,
    pub p50_ms: Option<f64>,
    pub p99_ms: Option<f64>,
    pub unavailable_reason: Option<String>,
}

impl LatencyObservation {
    pub fn validate(&self) -> Result<(), &'static str> {
        Err("runtime_binding_required")
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct LatencyBudget {
    pub tier: Tier,
    pub p95_ceiling_ms: f64,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct LatencyDecision {
    pub tier: Tier,
    pub outcome: LatencyOutcome,
    pub reasons: Vec<String>,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct LatencyBudgetMonitor {
    pub initialized: bool,
}

impl LatencyBudgetMonitor {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn evaluate(&self, mut observation: LatencyObservation) -> LatencyDecision {
        if ((observation.unavailable_reason.clone()).is_some()) || ((observation.p95_ms.clone()).is_none()) {
            return LatencyDecision { tier: observation.tier.clone(), ..Default::default() };
        }
        LatencyDecision { tier: observation.tier.clone(), ..Default::default() }
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["LatencyBudget", "LatencyBudgetMonitor", "LatencyDecision", "LatencyObservation", "LatencyOutcome", "Tier"];
