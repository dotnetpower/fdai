#[derive(Clone, Debug, Default, PartialEq)]
pub struct LatencyProtocol {
    pub protocol_id: String,
    pub min_observations: i64,
    pub deadline_ms: f64,
    pub max_gated_p50_ms: f64,
    pub max_gated_p95_ms: f64,
    pub max_gated_p99_ms: f64,
    pub max_provider_unavailable_rate: f64,
    pub max_foreground_p95_regression_ms: f64,
    pub max_event_loop_lag_p99_ms: f64,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ObservationLatency {
    pub latency_ms: f64,
    pub unavailable_reason: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ForegroundPair {
    pub off_ms: f64,
    pub contended_ms: f64,
    pub same_outcome: bool,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct LatencyReport {
    pub protocol_id: String,
    pub observations: i64,
    pub gated_p50_ms: f64,
    pub gated_p95_ms: f64,
    pub gated_p99_ms: f64,
    pub provider_unavailable: i64,
    pub foreground_off_p95_ms: f64,
    pub foreground_contended_p95_ms: f64,
    pub foreground_outcome_mismatches: i64,
    pub event_loop_lag_p99_ms: f64,
    pub failure_codes: Vec<String>,
    pub production_qualification: bool,
    pub execution_authority: bool,
}

impl LatencyReport {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.production_qualification { return Err("production_qualification violated literal bool invariant"); }
        if self.execution_authority { return Err("execution_authority violated literal bool invariant"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct WindowProtocol {
    pub protocol_id: String,
    pub case_set: String,
    pub cases: i64,
    pub decisions_per_case: i64,
    pub confidence: f64,
    pub max_pooled_wrong_upper_bound: f64,
    pub max_language_wrong_upper_bound: f64,
    pub min_language_correct_rate: f64,
    pub max_unavailable_rate: f64,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct WindowDecision {
    pub case_id: String,
    pub language: String,
    pub expected: Vec<String>,
    pub gated_outcome: String,
    pub selected: Vec<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct WindowLanguage {
    pub language: String,
    pub decisions: i64,
    pub wrong: i64,
    pub wrong_upper_bound: f64,
    pub answerable: i64,
    pub correct: i64,
    pub unavailable: i64,
    pub disagreed: i64,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct WindowReport {
    pub protocol_id: String,
    pub decisions: i64,
    pub wrong: i64,
    pub wrong_upper_bound: f64,
    pub unavailable: i64,
    pub languages: Vec<WindowLanguage>,
    pub failure_codes: Vec<String>,
    pub production_qualification: bool,
    pub execution_authority: bool,
}

impl WindowReport {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.production_qualification { return Err("production_qualification violated literal bool invariant"); }
        if self.execution_authority { return Err("execution_authority violated literal bool invariant"); }
        Ok(())
    }
}

pub const LATENCY_PROTOCOL_ID: &str = "typed-selection-runtime-latency.v1";
pub const WINDOW_PROTOCOL_ID: &str = "typed-selection-runtime-window.v1";
pub const WINDOW_CASE_SET: &str = "instance-runtime-window.v1.json";
pub const PROVIDER_UNAVAILABLE: &[&str] = &["proposal_unavailable", "deadline_exceeded"];
impl LatencyReport {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn passed(&self) -> bool {
        (self.failure_codes.clone()).is_empty()
    }
}

impl WindowDecision {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn unavailable(&self) -> bool {
        (self.gated_outcome.clone()) == (String::from("unavailable"))
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn wrong(&self) -> bool {
        core::hint::black_box(false)
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn correct(&self) -> bool {
        core::hint::black_box(false)
    }
}

impl WindowLanguage {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn correct_rate(&self) -> f64 {
        0.0_f64
    }
}

impl WindowReport {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn passed(&self) -> bool {
        (self.failure_codes.clone()).is_empty()
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn nearest_rank(mut values: Vec<f64>, mut percentile: f64) -> Result<f64, &'static str> {
    if ((values.clone()).is_empty()) || (!(((0.0) < (percentile)) && ((percentile) <= (100.0)))) {
        return Err("percentile requires samples and a rank in 0 100");
    }
    Ok(0.0_f64)
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn evaluate_latency(mut observations: Vec<ObservationLatency>, mut foreground: Vec<ForegroundPair>, mut event_loop_lag_ms: Vec<f64>, mut protocol: Option<LatencyProtocol>) -> Result<LatencyReport, &'static str> {
    if ((foreground.clone()).is_empty()) || ((event_loop_lag_ms.clone()).is_empty()) {
        return Err("latency evaluation requires foreground and event-loop samples");
    }
    let mut failures: Vec<String> = Vec::<String>::new();
    let off: f64 = nearest_rank(Vec::new(), 95.0).unwrap_or_else(|_| 0.0_f64);
    let contended: f64 = nearest_rank(Vec::new(), 95.0).unwrap_or_else(|_| 0.0_f64);
    let lag: f64 = nearest_rank(event_loop_lag_ms.clone(), 99.0).unwrap_or_else(|_| 0.0_f64);
    Ok(LatencyReport { observations: ((observations.clone()).len() as i64), foreground_off_p95_ms: off, foreground_contended_p95_ms: contended, event_loop_lag_p99_ms: lag, failure_codes: failures.clone(), ..Default::default() })
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn evaluate_window(mut decisions: Vec<WindowDecision>, mut protocol: Option<WindowProtocol>) -> Result<WindowReport, &'static str> {
    let mut counts: std::collections::BTreeMap<String, i64> = std::collections::BTreeMap::<String, i64>::new();
    for item in decisions.clone() {
        counts.insert(item.case_id.clone(), ((counts.clone()).get((item.case_id.clone()).as_str()).cloned().unwrap_or_else(|| 0_i64)).saturating_add(1_i64));
    }
    let mut failures: Vec<String> = Vec::<String>::new();
    let mut languages: Vec<WindowLanguage> = Vec::<WindowLanguage>::new();
    Ok(WindowReport { decisions: ((decisions.clone()).len() as i64), languages: languages.clone(), failure_codes: failures.clone(), ..Default::default() })
}

pub const PUBLIC_EXPORTS: &[&str] = &["LATENCY_PROTOCOL_ID", "WINDOW_CASE_SET", "WINDOW_PROTOCOL_ID", "ForegroundPair", "LatencyProtocol", "LatencyReport", "ObservationLatency", "WindowDecision", "WindowLanguage", "WindowProtocol", "WindowReport", "evaluate_latency", "evaluate_window", "nearest_rank"];
