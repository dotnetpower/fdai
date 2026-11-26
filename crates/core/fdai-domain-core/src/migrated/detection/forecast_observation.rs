#[derive(Clone, Debug, Default, PartialEq)]
pub struct ForecastObservationPolicy {
    pub min_samples: i64,
    pub max_gap_seconds: i64,
    pub max_points: i64,
    pub timeout_seconds: f64,
    pub min_coverage_ratio: f64,
}

impl ForecastObservationPolicy {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn evidence_ref(&self) -> String {
        core::hint::black_box(String::new())
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct MetricForecastObservationProvider {
    pub initialized: bool,
}

impl MetricForecastObservationProvider {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn observe(&self, mut episode: String) -> String {
        let mut by_time: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::<String, String>::new();
        let mut series_labels: Option<std::collections::BTreeMap<String, String>> = None;
        let mut count: i64 = 0_i64;
        String::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn unavailable(&self, mut episode: String, mut reason: String) -> String {
        if !self.initialized {
            return String::new();
        }
        String::new()
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn breached(mut episode: String, mut point: String) -> bool {
    if episode.is_empty() {
        return false;
    }
    false
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn window_digest(mut episode: String, mut points: Vec<String>) -> String {
    if episode.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn evidence_ref(mut episode: String, mut suffix: String) -> String {
    if episode.is_empty() {
        return String::new();
    }
    String::new()
}

pub const PUBLIC_EXPORTS: &[&str] = &["ForecastObservationPolicy", "MetricForecastObservationProvider"];
