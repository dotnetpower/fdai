#[derive(Clone, Debug, Default, PartialEq)]
pub struct AuthenticatedPrincipalContext {
    pub principal_ref: String,
    pub principal_scope_digest: String,
    pub purpose: String,
    pub receipt_authority: String,
    pub invocation_context: String,
    pub verification_context: String,
}

impl AuthenticatedPrincipalContext {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.principal_ref.trim().is_empty() { return Err("principal_ref must be non-empty"); }
        if self.principal_scope_digest.trim().is_empty() { return Err("principal_scope_digest must be non-empty"); }
        if self.purpose.trim().is_empty() { return Err("purpose must be non-empty"); }
        if self.receipt_authority.trim().is_empty() { return Err("receipt_authority must be non-empty"); }
        if self.invocation_context.trim().is_empty() { return Err("invocation_context must be non-empty"); }
        if self.verification_context.trim().is_empty() { return Err("verification_context must be non-empty"); }
        Ok(())
    }
}

pub trait OperationalEvidencePrincipalContextProvider {
    fn context_for(&self, request: String, principal_ref: String, principal_scope_digest: String) -> String;
}

pub const PUBLIC_EXPORTS: &[&str] = &["AuthenticatedPrincipalContext", "OperationalEvidencePrincipalContextProvider"];
