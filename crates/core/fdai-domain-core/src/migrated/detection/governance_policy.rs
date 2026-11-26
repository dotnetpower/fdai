#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum AnomalyMethod {
    #[default]
    ZScore,
    SeasonalZScore,
}

impl AnomalyMethod {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::ZScore => "z_score",
            Self::SeasonalZScore => "seasonal_z_score",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ForecastModelFamily {
    #[default]
    LinearTrend,
}

impl ForecastModelFamily {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::LinearTrend => "linear_trend",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct SignalClassPolicy {
    pub signal_class: String,
    pub anomaly_method: AnomalyMethod,
    pub min_baseline_samples: i64,
    pub seasonal_phase: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ForecastTargetPolicy {
    pub target_kind: String,
    pub model_family: ForecastModelFamily,
    pub horizon_seconds: i64,
    pub min_samples: i64,
    pub min_r_squared: f64,
    pub confidence_level: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CorrelationPolicy {
    pub exact_keys: Vec<String>,
    pub default_window_seconds: i64,
    pub trace_window_seconds: i64,
    pub t1_similarity_floor: f64,
    pub t1_min_shared_evidence_fields: i64,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ForecastPromotionPolicy {
    pub cadence_seconds: i64,
    pub min_scorable_episodes: i64,
    pub min_shadow_days: i64,
    pub min_precision: f64,
    pub min_recall: f64,
    pub min_interval_coverage: f64,
    pub max_interval_coverage: f64,
    pub min_median_lead_seconds: i64,
    pub max_abstention_rate: f64,
    pub max_policy_escapes: i64,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ChangeWindowPolicy {
    pub behavior: String,
    pub require_exact_scope: bool,
    pub require_complete_evidence: bool,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct DetectionGovernancePolicy {
    pub policy_id: String,
    pub policy_version: String,
    pub signal_classes: Vec<SignalClassPolicy>,
    pub forecast_targets: Vec<ForecastTargetPolicy>,
    pub correlation: Box<CorrelationPolicy>,
    pub forecast_promotion: Box<ForecastPromotionPolicy>,
    pub change_window: Box<ChangeWindowPolicy>,
    pub content_digest: String,
}

pub const DETECTION_GOVERNANCE_POLICY_PATH: &str = "config/detection-governance-policy.json";
pub const DETECTION_GOVERNANCE_SCHEMA_VERSION: &str = "1.0.0";
pub const DETECTION_GOVERNANCE_POLICY_ID: &str = "detection-governance";
pub const PHASES: &[&str] = &["hour_of_day", "day_of_week", "hour_of_week"];
pub const CORRELATION_KEYS: &[&str] = &["correlation_id", "resource_ref"];
pub const REQUIRED_CORRELATION_KEYS: &[&str] = &["correlation_id", "resource_ref"];
pub const FORECAST_CONFIDENCE_LEVELS: &[&str] = &["0.80", "0.90", "0.95", "0.99"];
pub const MIN_T1_SIMILARITY: f64 = 0.85;
impl DetectionGovernancePolicy {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn signal_class(&self, mut value: String) -> Result<SignalClassPolicy, &'static str> {
        for item in self.signal_classes.clone() {
            if (item.signal_class.clone()) == (value.clone()) {
                return Ok(item.clone());
            }
        }
        Err("unknown detection signal class valuer")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn forecast_target(&self, mut value: String) -> Result<ForecastTargetPolicy, &'static str> {
        for item in self.forecast_targets.clone() {
            if (item.target_kind.clone()) == (value.clone()) {
                return Ok(item.clone());
            }
        }
        Err("unknown forecast target kind valuer")
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn load_detection_governance_policy(mut path: String) -> Result<DetectionGovernancePolicy, &'static str> {
    Ok(DetectionGovernancePolicy { correlation: Box::new(correlation(String::new()).unwrap_or_else(|_| Default::default())), forecast_promotion: Box::new(promotion(String::new()).unwrap_or_else(|_| Default::default())), change_window: Box::new(change_window(String::new()).unwrap_or_else(|_| Default::default())), ..Default::default() })
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn signal_class(mut value: String, mut index: i64) -> Result<SignalClassPolicy, &'static str> {
    Ok(SignalClassPolicy::default())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn forecast_target(mut value: String, mut index: i64) -> Result<ForecastTargetPolicy, &'static str> {
    Ok(ForecastTargetPolicy::default())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn correlation(mut value: String) -> Result<CorrelationPolicy, &'static str> {
    Ok(CorrelationPolicy::default())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn promotion(mut value: String) -> Result<ForecastPromotionPolicy, &'static str> {
    Ok(ForecastPromotionPolicy::default())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn change_window(mut value: String) -> Result<ChangeWindowPolicy, &'static str> {
    Ok(ChangeWindowPolicy::default())
}

pub const PUBLIC_EXPORTS: &[&str] = &["DETECTION_GOVERNANCE_POLICY_PATH", "DETECTION_GOVERNANCE_POLICY_ID", "AnomalyMethod", "ChangeWindowPolicy", "CorrelationPolicy", "DetectionGovernancePolicy", "DetectionGovernancePolicyError", "ForecastModelFamily", "ForecastPromotionPolicy", "ForecastTargetPolicy", "SignalClassPolicy", "load_detection_governance_policy"];
