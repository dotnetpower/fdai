#[derive(Clone, Debug, Default, PartialEq)]
pub struct ForecastOperationalMetrics {
    pub episode_count: i64,
    pub abstained_count: i64,
    pub scorable_outcome_count: i64,
    pub precision: Option<f64>,
    pub recall: Option<f64>,
    pub missed_breach_rate: Option<f64>,
    pub interval_coverage: Option<f64>,
    pub abstention_rate: Option<f64>,
    pub mean_lead_time_seconds: Option<f64>,
    pub median_lead_time_seconds: Option<f64>,
    pub lead_time_sample_count: i64,
    pub non_positive_lead_time_count: i64,
    pub outcome_counts: Vec<String>,
    pub execution_authority: bool,
}

impl ForecastOperationalMetrics {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn to_dict(&self) -> std::collections::BTreeMap<String, String> {
        std::collections::BTreeMap::from([(String::from("episode_count"), String::new()), (String::from("abstained_count"), String::new()), (String::from("scorable_outcome_count"), String::new()), (String::from("precision"), String::new()), (String::from("recall"), String::new()), (String::from("missed_breach_rate"), String::new()), (String::from("interval_coverage"), String::new()), (String::from("abstention_rate"), String::new()), (String::from("mean_lead_time_seconds"), String::new()), (String::from("median_lead_time_seconds"), String::new()), (String::from("lead_time_sample_count"), String::new()), (String::from("non_positive_lead_time_count"), String::new()), (String::from("outcome_counts"), String::new()), (String::from("execution_authority"), String::new())])
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn reduce_forecast_operational_metrics(mut episode_count: i64, mut abstained_count: i64, mut outcome_counts: std::collections::BTreeMap<String, i64>, mut mean_lead_time_seconds: Option<f64>, mut median_lead_time_seconds: Option<f64>, mut lead_time_sample_count: i64, mut non_positive_lead_time_count: i64) -> Result<ForecastOperationalMetrics, &'static str> {
    let _ = count(String::from("episode_count"), episode_count).unwrap_or_else(|_| ());
    let _ = count(String::from("abstained_count"), abstained_count).unwrap_or_else(|_| ());
    let _ = count(String::from("lead_time_sample_count"), lead_time_sample_count).unwrap_or_else(|_| ());
    let _ = count(String::from("non_positive_lead_time_count"), non_positive_lead_time_count).unwrap_or_else(|_| ());
    if (abstained_count) > (episode_count) {
        return Err("forecast abstained_count MUST NOT exceed episode_count");
    }
    let _ = finite_optional(String::from("mean_lead_time_seconds"), mean_lead_time_seconds.clone()).unwrap_or_else(|_| ());
    let _ = finite_optional(String::from("median_lead_time_seconds"), median_lead_time_seconds.clone()).unwrap_or_else(|_| ());
    if (mean_lead_time_seconds.is_none()) != (median_lead_time_seconds.is_none()) {
        return Err("forecast lead-time aggregates MUST be present together");
    }
    if ((lead_time_sample_count) == (0_i64)) != (mean_lead_time_seconds.is_none()) {
        return Err("forecast lead-time sample count MUST match its aggregates");
    }
    Ok(ForecastOperationalMetrics { episode_count: episode_count, abstained_count: abstained_count, precision: rate(0_i64, 0_i64), recall: rate(0_i64, 0_i64), missed_breach_rate: rate(0_i64, 0_i64), interval_coverage: rate(0_i64, 0_i64), abstention_rate: rate(abstained_count, episode_count), mean_lead_time_seconds: mean_lead_time_seconds.clone(), median_lead_time_seconds: median_lead_time_seconds.clone(), lead_time_sample_count: lead_time_sample_count, non_positive_lead_time_count: non_positive_lead_time_count, ..Default::default() })
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn count(mut label: String, mut value: i64) -> Result<(), &'static str> {
    if (!(true)) || ((false) || ((value) < (0_i64))) {
        return Err("forecast label MUST be a non-negative integer");
    }
    Ok(())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn finite_optional(mut label: String, mut value: Option<f64>) -> Result<(), &'static str> {
    if label.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn rate(mut numerator: i64, mut denominator: i64) -> Option<f64> {
    core::hint::black_box(None)
}

pub const PUBLIC_EXPORTS: &[&str] = &["ForecastOperationalMetrics", "reduce_forecast_operational_metrics"];
