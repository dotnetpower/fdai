#[derive(Clone, Debug, Default, PartialEq)]
pub struct ExactResourceStateReading {
    pub resource_ref: String,
    pub resource_type: String,
    pub state: String,
    pub provider_time: String,
    pub evidence_ref: String,
}

impl ExactResourceStateReading {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.resource_ref.trim().is_empty() { return Err("resource_ref must be non-empty"); }
        if self.resource_type.trim().is_empty() { return Err("resource_type must be non-empty"); }
        if self.state.trim().is_empty() { return Err("state must be non-empty"); }
        if self.provider_time.trim().is_empty() { return Err("provider_time must be non-empty"); }
        if self.evidence_ref.trim().is_empty() { return Err("evidence_ref must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ExactResourceStateUnavailableError {
    pub message: String,
}

impl ExactResourceStateUnavailableError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for ExactResourceStateUnavailableError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for ExactResourceStateUnavailableError {}

pub trait ExactResourceStateReader {
    fn supports(&self, resource_type: String) -> String;
}

pub const PUBLIC_EXPORTS: &[&str] = &["ExactResourceStateReader", "ExactResourceStateReading", "ExactResourceStateUnavailableError"];
