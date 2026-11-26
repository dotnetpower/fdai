#[derive(Clone, Debug, Default, PartialEq)]
pub struct ReadLatencyProfile {
    pub sample_count: i64,
    pub failure_rate: f64,
    pub p50_ms: Option<i64>,
    pub p95_ms: Option<i64>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct PlanLatencyEstimate {
    pub lower_ms: i64,
    pub upper_ms: i64,
    pub measured: bool,
    pub sample_count: i64,
    pub multi_source: bool,
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn latency_profile(mut samples: Vec<String>) -> ReadLatencyProfile {
    let count: i64 = (samples.clone()).len() as i64;
    if (count) == (0_i64) {
        return ReadLatencyProfile { sample_count: 0_i64, failure_rate: 0.0, p50_ms: None, p95_ms: None, ..Default::default() };
    }
    ReadLatencyProfile { sample_count: count, p50_ms: percentile(Vec::new(), 0.5), p95_ms: percentile(Vec::new(), 0.95), ..Default::default() }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn estimate_plan_latency(mut plan: String, mut profiles: std::collections::BTreeMap<String, ReadLatencyProfile>, mut minimum_samples: i64) -> Result<PlanLatencyEstimate, &'static str> {
    if (false) || ((minimum_samples) < (1_i64)) {
        return Err("minimum_samples MUST be positive");
    }
    Ok(PlanLatencyEstimate::default())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn estimate_sequential_p95(mut profiles: Vec<ReadLatencyProfile>) -> Option<i64> {
    if profiles.is_empty() {
        return None;
    }
    None
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn estimate_parallel_p95(mut profiles: Vec<ReadLatencyProfile>) -> Option<i64> {
    if profiles.is_empty() {
        return None;
    }
    None
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn tool_estimate(mut tool_id: String, mut profile: Option<ReadLatencyProfile>, mut minimum_samples: i64) -> (i64, i64, bool, i64) {
    (0_i64, 0_i64, false, 0_i64)
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn percentile(mut values: Vec<i64>, mut quantile: f64) -> Option<i64> {
    if (values.clone()).is_empty() {
        return None;
    }
    None
}

pub const PUBLIC_EXPORTS: &[&str] = &["PlanLatencyEstimate", "ReadLatencyProfile", "estimate_parallel_p95", "estimate_plan_latency", "estimate_sequential_p95", "latency_profile"];
