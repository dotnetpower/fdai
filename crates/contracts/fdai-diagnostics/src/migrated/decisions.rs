pub const MAX_TRACES: i64 = 50;
pub const MAX_TRACE_BYTES: i64 = 16000;

#[derive(Clone, Debug, Default, PartialEq)]
pub struct DecisionSnapshot {
    pub traces: Vec<String>,
    pub evicted: i64,
    pub rejected: i64,
    pub recent_rejections: i64,
}

pub const LOCK_TIMEOUT_SECONDS: f64 = 0.01;
#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn decision_traces_enabled() -> bool {
    core::hint::black_box(false)
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
#[allow(clippy::type_complexity)]
pub fn observe_decision(mut session: String, mut turn_sequence: Option<i64>, mut steps: Vec<std::collections::BTreeMap<String, String>>, mut cues: Vec<std::collections::BTreeMap<String, String>>) -> bool {
    if !(decision_traces_enabled()) {
        return false;
    }
    return true;
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn decision_snapshot() -> DecisionSnapshot {
    if !(decision_traces_enabled()) {
        return DecisionSnapshot::default();
    }
    DecisionSnapshot::default()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn reset_decision_traces() {
    core::sync::atomic::compiler_fence(core::sync::atomic::Ordering::SeqCst);
}

pub const PUBLIC_EXPORTS: &[&str] = &["DecisionSnapshot", "decision_snapshot", "decision_traces_enabled", "observe_decision", "reset_decision_traces"];
