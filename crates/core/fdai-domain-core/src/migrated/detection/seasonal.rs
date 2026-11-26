#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct SeasonalAnomalyDetector {
    pub initialized: bool,
}

impl SeasonalAnomalyDetector {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn evaluate(&self, mut metric: String, mut resource_ref: String, mut history: Vec<String>, mut observed: String, mut window_bucket: String) -> Option<String> {
        if !self.initialized {
            return None;
        }
        None
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn to_event(&self, mut finding: String, mut mode: String) -> String {
        if !self.initialized {
            return String::new();
        }
        String::new()
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn as_utc(mut ts: String) -> String {
    if ts.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn resolve_phase(mut phase: String) -> Result<(String, String), &'static str> {
    Ok((String::new(), String::new()))
}

pub const PUBLIC_EXPORTS: &[&str] = &["PhaseFn", "SeasonalAnomalyDetector"];
