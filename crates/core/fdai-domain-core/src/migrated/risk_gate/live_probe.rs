use std::collections::BTreeMap;
pub const FAILURE_ESCALATION_THRESHOLD: i64 = 3;

#[derive(Clone, Debug, Default, PartialEq)]
pub struct LiveProbeObservation {
    pub probe_id: String,
    pub verdict: String,
    pub degraded: bool,
    pub age_seconds: Option<f64>,
    pub max_age_seconds: Option<f64>,
    pub reason: String,
    #[allow(clippy::type_complexity)]
    pub metrics: Option<BTreeMap<String, f64>>,
}

impl LiveProbeObservation {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.probe_id.trim().is_empty() { return Err("probe_id must be non-empty"); }
        if self.verdict.trim().is_empty() { return Err("verdict must be non-empty"); }
        if self.reason.trim().is_empty() { return Err("reason must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct LiveProbeAxis {
    pub result: Option<String>,
    pub reason: String,
}

impl LiveProbeObservation {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn is_fresh(&self) -> bool {
        if (self.age_seconds.is_none()) || (self.max_age_seconds.is_none()) {
            return false;
        }
        false
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn floor_at_active(mut candidate: String) -> String {
    if candidate.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn resolve_live_probe_axis(mut action_type: String, mut observation: Option<LiveProbeObservation>, mut failure_streak: i64) -> LiveProbeAxis {
    if (failure_streak) >= (FAILURE_ESCALATION_THRESHOLD) {
        return LiveProbeAxis::default();
    }
    let Some(mut observation) = observation.clone() else { return LiveProbeAxis::default(); };
    if observation.degraded {
        return LiveProbeAxis::default();
    }
    LiveProbeAxis::default()
}

pub const PUBLIC_EXPORTS: &[&str] = &["FAILURE_ESCALATION_THRESHOLD", "LiveProbeAxis", "LiveProbeObservation", "resolve_live_probe_axis"];
