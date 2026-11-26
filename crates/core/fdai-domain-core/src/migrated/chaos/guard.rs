use std::collections::BTreeMap;
#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ChaosStopReason {
    #[default]
    AffectedSetExceeded,
    DurationExceeded,
    ObjectiveBoundExceeded,
    ForbiddenSignal,
    TelemetryIncomplete,
    BackendUnreachable,
}

impl ChaosStopReason {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::AffectedSetExceeded => "affected_set_exceeded",
            Self::DurationExceeded => "duration_exceeded",
            Self::ObjectiveBoundExceeded => "objective_bound_exceeded",
            Self::ForbiddenSignal => "forbidden_signal",
            Self::TelemetryIncomplete => "telemetry_incomplete",
            Self::BackendUnreachable => "backend_unreachable",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ImpactObservation {
    pub observed_resources: Vec<String>,
    pub signals: Vec<String>,
    pub objective_values: BTreeMap<String, f64>,
    pub source_observed_at: BTreeMap<String, String>,
    pub elapsed_seconds: f64,
    pub injector_reachable: bool,
    pub recovery_reachable: bool,
}

impl ImpactObservation {
    pub fn validate(&self) -> Result<(), &'static str> {
        Err("runtime_binding_required")
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ChaosStopEvent {
    pub run_id: String,
    pub impact_envelope_id: String,
    pub reason: ChaosStopReason,
    pub observed_resources: Vec<String>,
    pub observed_signals: Vec<String>,
    pub occurred_at: String,
    pub detail: String,
}

impl ChaosStopEvent {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn to_payload(&self) -> std::collections::BTreeMap<String, String> {
        std::collections::BTreeMap::from([(String::from("event_type"), String::from("chaos.stop-triggered")), (String::from("run_id"), self.run_id.clone()), (String::from("impact_envelope_id"), self.impact_envelope_id.clone()), (String::from("reason"), String::new()), (String::from("observed_resources"), String::new()), (String::from("observed_signals"), String::new()), (String::from("occurred_at"), String::new()), (String::from("detail"), self.detail.clone())])
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn evaluate_impact_guard(mut run_id: String, mut envelope: String, mut observation: ImpactObservation, mut now: String) -> Result<Option<ChaosStopEvent>, &'static str> {
    let stop: Option<(ChaosStopReason, String)> = stop_reason(envelope.clone(), observation.clone(), now.clone());
    let Some(mut stop) = stop.clone() else { return Ok(None); };
    Ok(Some(ChaosStopEvent { run_id: run_id.clone(), observed_resources: { let mut _v = observation.observed_resources.clone(); _v.sort(); _v }, observed_signals: { let mut _v = observation.signals.clone(); _v.sort(); _v }, occurred_at: now.clone(), ..Default::default() }))
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
#[allow(clippy::type_complexity)]
pub fn stop_reason(mut envelope: String, mut observation: ImpactObservation, mut now: String) -> Option<(ChaosStopReason, String)> {
    if envelope.is_empty() {
        return None;
    }
    None
}

pub const PUBLIC_EXPORTS: &[&str] = &["ChaosStopEvent", "ChaosStopReason", "evaluate_impact_guard", "ImpactGuard", "ImpactObservation"];
