use std::collections::BTreeMap;
#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum CostConfidence {
    #[default]
    High,
    Medium,
    Low,
    Abstain,
}

impl CostConfidence {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::High => "high",
            Self::Medium => "medium",
            Self::Low => "low",
            Self::Abstain => "abstain",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CostEstimate {
    pub monthly_usd: Option<f64>,
    pub confidence: CostConfidence,
    pub estimator_id: String,
    pub rationale: Option<String>,
    pub metadata: BTreeMap<String, String>,
}

impl CostEstimate {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn abstained(&self) -> bool {
        core::hint::black_box(false)
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn to_dict(&self) -> std::collections::BTreeMap<String, String> {
        std::collections::BTreeMap::from([(String::from("monthly_usd"), String::new()), (String::from("confidence"), String::new()), (String::from("estimator_id"), self.estimator_id.clone()), (String::from("rationale"), (self.rationale.clone()).unwrap_or_default()), (String::from("metadata"), String::new())])
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct CostEstimatorError {
    pub message: String,
}

impl CostEstimatorError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for CostEstimatorError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for CostEstimatorError {}

pub trait CostEstimator {
    fn estimate(&self, action_type: String, arguments: std::collections::BTreeMap<String, String>) -> CostEstimate;
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub async fn resolve_cost_impact_monthly(mut estimator: Option<String>, mut action_type: String, mut arguments: Option<std::collections::BTreeMap<String, String>>) -> Option<f64> {
    let Some(mut estimator) = estimator.clone() else { return None; };
    None
}

pub const PUBLIC_EXPORTS: &[&str] = &["CostConfidence", "CostEstimate", "CostEstimator", "CostEstimatorError", "resolve_cost_impact_monthly"];
