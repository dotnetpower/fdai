#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct OperationalEvidenceUnavailableError {
    pub message: String,
}

impl OperationalEvidenceUnavailableError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for OperationalEvidenceUnavailableError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for OperationalEvidenceUnavailableError {}

pub trait OperationalEvidenceIssuer {
    fn issue(&self, request: String) -> String;
}

pub trait OperationalEvidenceOutcomeReader {
    fn outcome(&self, response: String, lookup: String) -> String;
}

pub const PUBLIC_EXPORTS: &[&str] = &["OperationalEvidenceIssuer", "OperationalEvidenceOutcomeReader", "OperationalEvidenceUnavailableError"];
