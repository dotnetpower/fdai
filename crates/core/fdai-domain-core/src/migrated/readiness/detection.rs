#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum DetectionReadinessDimension {
    #[default]
    Discovered,
    CollectorConfigured,
    TelemetryObserved,
    DetectorBound,
    PipelineObserved,
    ActionGoverned,
}

impl DetectionReadinessDimension {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Discovered => "discovered",
            Self::CollectorConfigured => "collector_configured",
            Self::TelemetryObserved => "telemetry_observed",
            Self::DetectorBound => "detector_bound",
            Self::PipelineObserved => "pipeline_observed",
            Self::ActionGoverned => "action_governed",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum DetectionObservationStatus {
    #[default]
    Passed,
    Failed,
    Unavailable,
    Unauthorized,
}

impl DetectionObservationStatus {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Passed => "passed",
            Self::Failed => "failed",
            Self::Unavailable => "unavailable",
            Self::Unauthorized => "unauthorized",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum DetectionReadinessDecision {
    #[default]
    Ready,
    Partial,
    Blocked,
    Stale,
    Unauthorized,
    Unknown,
}

impl DetectionReadinessDecision {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Ready => "ready",
            Self::Partial => "partial",
            Self::Blocked => "blocked",
            Self::Stale => "stale",
            Self::Unauthorized => "unauthorized",
            Self::Unknown => "unknown",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct DetectionReadinessObservation {
    pub resource_ref: String,
    pub dimension: DetectionReadinessDimension,
    pub status: DetectionObservationStatus,
    pub observed_at: String,
    pub expires_at: String,
    pub source: String,
    pub evidence_digest: String,
    pub detail_code: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct DetectionReadinessSnapshot {
    pub resource_ref: String,
    pub generated_at: String,
    pub decision: DetectionReadinessDecision,
    pub observations: Vec<DetectionReadinessObservation>,
    pub missing_dimensions: Vec<DetectionReadinessDimension>,
    pub stale_dimensions: Vec<DetectionReadinessDimension>,
    pub authority_ceiling: String,
}

pub const DETECTION_READINESS_STATE_PREFIX: &str = "runtime:detection-readiness:";
impl DetectionReadinessObservation {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn require_timezone(mut value: String) -> Result<String, &'static str> {
        Ok(value.clone())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn validate_observation(&self) -> Result<DetectionReadinessObservation, &'static str> {
        if (self.expires_at.clone()) <= (self.observed_at.clone()) {
            return Err("detection readiness expiry MUST follow observation time");
        }
        Ok(self.clone())
    }
}

impl DetectionReadinessSnapshot {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn require_generated_timezone(mut value: String) -> Result<String, &'static str> {
        Ok(value.clone())
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn reduce_detection_readiness(mut observations: Vec<DetectionReadinessObservation>, mut resource_ref: String, mut generated_at: String, mut deployment_ceiling: String) -> Result<DetectionReadinessSnapshot, &'static str> {
    let mut ceiling: String = deployment_ceiling.clone();
    Ok(DetectionReadinessSnapshot { resource_ref: resource_ref.clone(), generated_at: generated_at.clone(), authority_ceiling: ceiling.clone(), ..Default::default() })
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn detection_readiness_state_key(mut resource_ref: String) -> Result<String, &'static str> {
    if (resource_ref.trim().to_string()).is_empty() {
        return Err("detection readiness resource_ref MUST be non-empty");
    }
    Ok(String::new())
}

pub const PUBLIC_EXPORTS: &[&str] = &["DETECTION_READINESS_STATE_PREFIX", "DetectionObservationStatus", "DetectionReadinessDecision", "DetectionReadinessDimension", "DetectionReadinessObservation", "DetectionReadinessSnapshot", "detection_readiness_state_key", "reduce_detection_readiness"];
