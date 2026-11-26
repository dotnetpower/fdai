#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum FrameworkObservationOutcome {
    #[default]
    Satisfied,
    Failed,
    Unknown,
}

impl FrameworkObservationOutcome {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Satisfied => "satisfied",
            Self::Failed => "failed",
            Self::Unknown => "unknown",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct FrameworkObservationRequest {
    pub framework_id: String,
    pub catalog_digest: String,
    pub scope_digest: String,
    pub control_ids: Vec<String>,
    pub inventory_generation: Option<String>,
    pub hierarchy_generation: Option<String>,
    pub evaluated_at: String,
    pub maximum_observations: i64,
    pub timeout_seconds: i64,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct FrameworkProviderObservation {
    pub control_id: String,
    pub requirement_ref: String,
    pub evidence_ref: String,
    pub evidence_kind: String,
    pub producer: String,
    pub source_identity: String,
    pub observed_at: String,
    pub recorded_at: String,
    pub evidence_digest: String,
    pub complete: bool,
    pub truncated: bool,
    pub conflicting: bool,
    pub synthetic: bool,
    pub provider_error: Option<String>,
    pub outcome: FrameworkObservationOutcome,
}

impl FrameworkProviderObservation {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.control_id.trim().is_empty() { return Err("control_id must be non-empty"); }
        if self.requirement_ref.trim().is_empty() { return Err("requirement_ref must be non-empty"); }
        if self.evidence_ref.trim().is_empty() { return Err("evidence_ref must be non-empty"); }
        if self.evidence_kind.trim().is_empty() { return Err("evidence_kind must be non-empty"); }
        if self.producer.trim().is_empty() { return Err("producer must be non-empty"); }
        if self.source_identity.trim().is_empty() { return Err("source_identity must be non-empty"); }
        if self.observed_at.trim().is_empty() { return Err("observed_at must be non-empty"); }
        if self.recorded_at.trim().is_empty() { return Err("recorded_at must be non-empty"); }
        if self.evidence_digest.trim().is_empty() { return Err("evidence_digest must be non-empty"); }
        Ok(())
    }
}

pub const SHA256: &str = "^sha256:[a-f0-9]{64}$";
pub trait FrameworkAssessmentObservationProvider {
    fn observe(&self, request: FrameworkObservationRequest) -> Vec<FrameworkProviderObservation>;
}

pub const PUBLIC_EXPORTS: &[&str] = &["FrameworkAssessmentObservationProvider", "FrameworkObservationOutcome", "FrameworkObservationRequest", "FrameworkProviderObservation"];
