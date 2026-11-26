use std::collections::BTreeMap;
#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ExperimentOutcome {
    #[default]
    Shadowed,
    Validated,
    NotDetected,
    BlastRadiusExceeded,
    Aborted,
    RollbackFailed,
}

impl ExperimentOutcome {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Shadowed => "shadowed",
            Self::Validated => "validated",
            Self::NotDetected => "not_detected",
            Self::BlastRadiusExceeded => "blast_radius_exceeded",
            Self::Aborted => "aborted",
            Self::RollbackFailed => "rollback_failed",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct FaultScenario {
    pub scenario_id: String,
    pub fault_type: String,
    pub description: String,
    pub target_selector: String,
    pub expected_signal: String,
    pub blast_radius_cap: i64,
    pub duration_seconds: f64,
    pub params: BTreeMap<String, String>,
    pub rollback_note: String,
}

impl FaultScenario {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.scenario_id.trim().is_empty() { return Err("scenario_id must be non-empty"); }
        if self.fault_type.trim().is_empty() { return Err("fault_type must be non-empty"); }
        if self.description.trim().is_empty() { return Err("description must be non-empty"); }
        if self.target_selector.trim().is_empty() { return Err("target_selector must be non-empty"); }
        if self.expected_signal.trim().is_empty() { return Err("expected_signal must be non-empty"); }
        if self.rollback_note.trim().is_empty() { return Err("rollback_note must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ExperimentResult {
    pub experiment_id: String,
    pub scenario_id: String,
    pub mode: String,
    pub targets: Vec<String>,
    pub outcome: ExperimentOutcome,
    pub expected_signal: String,
    pub detected: bool,
    pub started_at: String,
    pub ended_at: String,
    pub injected: bool,
    pub stopped: bool,
    pub injected_at: Option<String>,
    pub detection_observed_at: Option<String>,
    pub error: Option<String>,
    pub stop_reason: Option<String>,
}

impl ExperimentResult {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.experiment_id.trim().is_empty() { return Err("experiment_id must be non-empty"); }
        if self.scenario_id.trim().is_empty() { return Err("scenario_id must be non-empty"); }
        if self.mode.trim().is_empty() { return Err("mode must be non-empty"); }
        if self.expected_signal.trim().is_empty() { return Err("expected_signal must be non-empty"); }
        if self.started_at.trim().is_empty() { return Err("started_at must be non-empty"); }
        if self.ended_at.trim().is_empty() { return Err("ended_at must be non-empty"); }
        Ok(())
    }
}

impl ExperimentResult {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn reverted(&self) -> bool {
        (self.stopped) || (!(self.injected))
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn detection_latency_seconds(&self) -> Option<f64> {
        if (self.injected_at.is_none()) || (self.detection_observed_at.is_none()) {
            return None;
        }
        None
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["ExperimentOutcome", "ExperimentResult", "FaultScenario"];
