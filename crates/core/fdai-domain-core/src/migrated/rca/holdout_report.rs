#[derive(Clone, Debug, Default, PartialEq)]
pub struct RateInterval {
    pub numerator: i64,
    pub denominator: i64,
    pub rate: f64,
    pub ci_low: f64,
    pub ci_high: f64,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CohortIntervalSummary {
    pub receipt: String,
    pub root_cause_accuracy: Box<RateInterval>,
    pub cause_recall: Box<RateInterval>,
    pub correct_abstention_rate: Box<RateInterval>,
    pub wrong_action_rate: Box<RateInterval>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CausalHoldoutEvaluationReport {
    pub calibration: Box<CohortIntervalSummary>,
    pub holdout: Box<CohortIntervalSummary>,
    pub report_digest: String,
    pub deployed_qualification: bool,
    pub execution_authority: bool,
}

pub const Z_95: f64 = 1.959963984540054;
#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn wilson_interval(mut numerator: i64, mut denominator: i64) -> Result<RateInterval, &'static str> {
    if ((denominator) < (0_i64)) || (((numerator) < (0_i64)) || ((numerator) > (denominator))) {
        return Err("wilson_interval requires 0  numerator  denominator");
    }
    if (denominator) == (0_i64) {
        return Ok(RateInterval { numerator: 0_i64, denominator: 0_i64, rate: 0.0, ci_low: 0.0, ci_high: 0.0, ..Default::default() });
    }
    let n: f64 = (denominator) as f64;
    let z2: f64 = (Z_95) * (Z_95);
    Ok(RateInterval { numerator: numerator, denominator: denominator, ..Default::default() })
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn summarize_cohort_intervals(mut receipt: String) -> CohortIntervalSummary {
    CohortIntervalSummary { receipt: receipt.clone(), root_cause_accuracy: Box::new(wilson_interval(0_i64, 0_i64).unwrap_or_else(|_| Default::default())), cause_recall: Box::new(wilson_interval(0_i64, 0_i64).unwrap_or_else(|_| Default::default())), correct_abstention_rate: Box::new(wilson_interval(0_i64, 0_i64).unwrap_or_else(|_| Default::default())), wrong_action_rate: Box::new(wilson_interval(0_i64, 0_i64).unwrap_or_else(|_| Default::default())), ..Default::default() }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn evaluate_disjoint_causal_holdout(mut calibration_cases: Vec<String>, mut calibration_results: Vec<String>, mut holdout_cases: Vec<String>, mut holdout_results: Vec<String>, mut runner_id: String, mut runner_source_revision: String, mut runner_method: String) -> Result<CausalHoldoutEvaluationReport, &'static str> {
    let cal_summary: CohortIntervalSummary = summarize_cohort_intervals(String::new());
    let hold_summary: CohortIntervalSummary = summarize_cohort_intervals(String::new());
    Ok(CausalHoldoutEvaluationReport { calibration: Box::new(cal_summary.clone()), holdout: Box::new(hold_summary.clone()), ..Default::default() })
}

pub const PUBLIC_EXPORTS: &[&str] = &["CausalHoldoutEvaluationReport", "CohortIntervalSummary", "RateInterval", "evaluate_disjoint_causal_holdout", "summarize_cohort_intervals", "wilson_interval"];
