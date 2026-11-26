#[derive(Clone, Debug, Default, PartialEq)]
pub struct ForecastContextRequest {
    pub access_scope_digest: String,
    pub target_digest: String,
    pub horizon_started_at: String,
    pub horizon_ended_at: String,
    pub as_of: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ForecastContextEvidence {
    pub access_scope_digest: String,
    pub target_digest: String,
    pub horizon_started_at: String,
    pub horizon_ended_at: String,
    pub recorded_at: String,
    pub valid_until: String,
    pub complete: bool,
    pub source_revision: String,
    pub evidence_refs: Vec<String>,
    pub intervention_refs: Vec<String>,
    pub resource_deleted: bool,
    pub excluded_window: bool,
}

impl ForecastContextEvidence {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.access_scope_digest.trim().is_empty() { return Err("access_scope_digest must be non-empty"); }
        if self.target_digest.trim().is_empty() { return Err("target_digest must be non-empty"); }
        if self.horizon_started_at.trim().is_empty() { return Err("horizon_started_at must be non-empty"); }
        if self.horizon_ended_at.trim().is_empty() { return Err("horizon_ended_at must be non-empty"); }
        if self.recorded_at.trim().is_empty() { return Err("recorded_at must be non-empty"); }
        if self.valid_until.trim().is_empty() { return Err("valid_until must be non-empty"); }
        if self.source_revision.trim().is_empty() { return Err("source_revision must be non-empty"); }
        Ok(())
    }
}

impl ForecastContextEvidence {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn digest(&self) -> String {
        core::hint::black_box(String::new())
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ForecastContextUnavailableError {
    pub message: String,
}

impl ForecastContextUnavailableError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for ForecastContextUnavailableError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for ForecastContextUnavailableError {}

pub trait ForecastContextProvider {
    fn read(&self, request: ForecastContextRequest) -> String;
}

