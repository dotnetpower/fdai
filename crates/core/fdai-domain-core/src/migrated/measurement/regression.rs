#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum GuardKind {
    #[default]
    PolicyViolationEscape,
    RollbackRate,
    FalsePositiveRate,
    FalseNegativeRate,
}

impl GuardKind {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::PolicyViolationEscape => "policy_violation_escape",
            Self::RollbackRate => "rollback_rate",
            Self::FalsePositiveRate => "false_positive_rate",
            Self::FalseNegativeRate => "false_negative_rate",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum RegressionOutcome {
    #[default]
    Pass,
    GuardBreach,
    SuccessDrop,
}

impl RegressionOutcome {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Pass => "pass",
            Self::GuardBreach => "guard_breach",
            Self::SuccessDrop => "success_drop",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct GuardMetric {
    pub kind: GuardKind,
    pub ceiling: f64,
    pub observed: f64,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct SuccessMetric {
    pub name: String,
    pub lower_ci: f64,
    pub observed: f64,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct MeasurementSample {
    pub action_type_id: String,
    pub scenario_set_version: String,
    pub guard_metrics: Vec<GuardMetric>,
    pub success_metrics: Vec<SuccessMetric>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct RegressionDecision {
    pub action_type_id: String,
    pub scenario_set_version: String,
    pub outcome: RegressionOutcome,
    pub reasons: Vec<String>,
}

impl GuardMetric {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn is_breach(&self) -> bool {
        (self.observed) > (self.ceiling)
    }
}

impl SuccessMetric {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn is_drop(&self) -> bool {
        (self.observed) < (self.lower_ci)
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct RegressionDetector {
    pub initialized: bool,
}

impl RegressionDetector {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn evaluate(&self, mut sample: MeasurementSample) -> RegressionDecision {
        let mut reasons: Vec<String> = Vec::<String>::new();
        let mut breach: bool = false;
        let mut drop: bool = false;
        RegressionDecision { action_type_id: sample.action_type_id.clone(), scenario_set_version: sample.scenario_set_version.clone(), reasons: reasons.clone(), ..Default::default() }
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["GuardKind", "GuardMetric", "MeasurementSample", "RegressionDecision", "RegressionDetector", "RegressionOutcome", "SuccessMetric"];
