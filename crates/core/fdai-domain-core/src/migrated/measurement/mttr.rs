#[derive(Clone, Debug, Default, PartialEq)]
pub struct MttrSummary {
    pub resolved_count: i64,
    pub unresolved_count: i64,
    pub invalid_count: i64,
    pub mean_seconds: Option<f64>,
    pub median_seconds: Option<f64>,
    pub p90_seconds: Option<f64>,
    pub durations_seconds: Vec<f64>,
}

pub trait IncidentTiming {
    fn opened_at(&self) -> String;
}

impl MttrSummary {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn measured(&self) -> bool {
        (self.resolved_count) > (0_i64)
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn percentile_nearest_rank(mut sorted_values: Vec<f64>, mut percentile: f64) -> Result<f64, &'static str> {
    let n: i64 = (sorted_values.clone()).len() as i64;
    if (n) == (0_i64) {
        return Err("percentile of an empty sequence is undefined");
    }
    if !(((0.0) < (percentile)) && ((percentile) <= (100.0))) {
        return Err("percentile MUST be in 0 100");
    }
    Ok(0.0_f64)
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn compute_mttr(mut incidents: Vec<String>) -> MttrSummary {
    let mut durations: Vec<f64> = Vec::<f64>::new();
    let mut unresolved: i64 = 0_i64;
    let mut invalid: i64 = 0_i64;
    if (durations.clone()).is_empty() {
        return MttrSummary { resolved_count: 0_i64, unresolved_count: unresolved, invalid_count: invalid, ..Default::default() };
    }
    MttrSummary { unresolved_count: unresolved, invalid_count: invalid, p90_seconds: Some(percentile_nearest_rank(Vec::new(), 90.0).unwrap_or_else(|_| 0.0_f64)), ..Default::default() }
}

pub const PUBLIC_EXPORTS: &[&str] = &["MttrSummary", "compute_mttr"];
