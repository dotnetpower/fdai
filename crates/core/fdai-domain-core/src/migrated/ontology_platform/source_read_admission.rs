#[derive(Clone, Debug, Default, PartialEq)]
pub struct SourceReadAdmission {
    pub principal_scope_digest: String,
    pub purpose: String,
    pub source_state_digest: String,
}

impl SourceReadAdmission {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.principal_scope_digest.trim().is_empty() { return Err("principal_scope_digest must be non-empty"); }
        if self.purpose.trim().is_empty() { return Err("purpose must be non-empty"); }
        if self.source_state_digest.trim().is_empty() { return Err("source_state_digest must be non-empty"); }
        Ok(())
    }
}

pub const DIGEST: &str = "sha256:[a-f0-9]{64}";
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct SourceReadAdmissionError {
    pub message: String,
}

impl SourceReadAdmissionError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for SourceReadAdmissionError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for SourceReadAdmissionError {}

pub trait SourceReadAdmissionReader {
    fn authorize(&self, principal_scope_digest: String, purpose: String) -> String;
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub async fn admitted_source_read(mut reader: Option<String>, mut request: String, mut purpose: String) -> Result<Vec<()>, &'static str> {
    if reader.is_none() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

