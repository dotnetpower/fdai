pub const DEFAULT_MAX_POLICY_ESCAPES: i64 = 0;
pub const DEFAULT_MAX_MISSING_EXPECTED_RULES: i64 = 0;

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum RegressionOutcome {
    #[default]
    Pass,
    Fail,
}

impl RegressionOutcome {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Pass => "pass",
            Self::Fail => "fail",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct RegressionGateConfig {
    pub max_policy_escapes: i64,
    pub min_coverage_ratio: f64,
    pub max_missing_expected_rules: i64,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct RegressionDecision {
    pub outcome: RegressionOutcome,
    pub scenario_set_id: String,
    pub candidate_rule_ids: Vec<String>,
    pub baseline_coverage: f64,
    pub candidate_coverage: f64,
    pub policy_violation_escapes: i64,
    pub missing_expected_rules: i64,
    pub reasons: Vec<String>,
}

pub const DEFAULT_MIN_COVERAGE_RATIO: f64 = 0.95;
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct RegressionGate {
    pub initialized: bool,
}

impl RegressionGate {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn evaluate(&self, mut candidate: String, mut baseline: Option<String>) -> RegressionDecision {
        let mut reasons: Vec<String> = Vec::<String>::new();
        RegressionDecision { reasons: reasons.clone(), ..Default::default() }
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["RegressionDecision", "RegressionGate", "RegressionGateConfig", "RegressionOutcome"];
