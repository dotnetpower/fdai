#[derive(Clone, Debug, Default, PartialEq)]
pub struct ForecastExpectation {
    pub prediction_id: String,
    pub correlation_id: String,
    pub detector_id: String,
    pub detector_version: String,
    pub access_scope_digest: String,
    pub target_ref: String,
    pub metric: String,
    pub feature_cutoff: String,
    pub horizon_started_at: String,
    pub horizon_ended_at: String,
    pub direction: String,
    pub threshold: f64,
    pub predicted_value: f64,
    pub interval_lower: f64,
    pub interval_upper: f64,
    pub evidence_refs: Vec<String>,
    pub mode: String,
}

impl ForecastExpectation {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.direction.as_str(), "rising" | "falling") { return Err("invalid direction literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ForecastObservation {
    pub observed_value: Option<f64>,
    pub actual_breach_at: Option<String>,
    pub telemetry_completeness: String,
    pub evidence_refs: Vec<String>,
    pub intervention_refs: Vec<String>,
    pub scoring_exclusions: Vec<String>,
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn forecast_outcome_schema_version(mut exclusions: Vec<String>) -> String {
    let values: std::collections::BTreeSet<String> = (exclusions.clone()).into_iter().collect::<std::collections::BTreeSet<String>>();
    if !(values.clone()).is_empty() { String::from("1.1.0") } else { String::from("1.0.0") }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn close_forecast(mut expectation: ForecastExpectation, mut observation: ForecastObservation, mut closed_at: String) -> String {
    let label: String = label(expectation.clone(), observation.clone());
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
#[allow(clippy::too_many_arguments)]
pub fn close_missed_breach(mut correlation_id: String, mut detector_id: String, mut detector_version: String, mut access_scope_digest: String, mut target_ref: String, mut metric: String, mut feature_cutoff: String, mut horizon_started_at: String, mut horizon_ended_at: String, mut direction: String, mut threshold: f64, mut observed_value: f64, mut actual_breach_at: String, mut evidence_refs: Vec<String>, mut closed_at: String, mut miss_origin: String) -> String {
    if correlation_id.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn label(mut expectation: ForecastExpectation, mut observation: ForecastObservation) -> String {
    core::hint::black_box(String::new())
}

pub const PUBLIC_EXPORTS: &[&str] = &["ForecastExpectation", "ForecastObservation", "close_forecast", "close_missed_breach"];
