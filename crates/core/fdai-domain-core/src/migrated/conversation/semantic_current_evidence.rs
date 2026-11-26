#[derive(Clone, Debug, Default, PartialEq)]
pub struct SemanticCurrentEvidenceObservation {
    pub function_name: String,
    pub complete: bool,
    pub authority: String,
    pub principal_scope_digest: String,
    pub incomplete_reason: Option<String>,
}

impl SemanticCurrentEvidenceObservation {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.function_name.trim().is_empty() { return Err("function_name must be non-empty"); }
        if self.authority.trim().is_empty() { return Err("authority must be non-empty"); }
        if self.principal_scope_digest.trim().is_empty() { return Err("principal_scope_digest must be non-empty"); }
        Ok(())
    }
}

pub trait SemanticCurrentEvidenceProbe {
    fn observe(&self, function_name: String, principal: String) -> String;
}

pub const PUBLIC_EXPORTS: &[&str] = &["SemanticCurrentEvidenceObservation", "SemanticCurrentEvidenceProbe"];
