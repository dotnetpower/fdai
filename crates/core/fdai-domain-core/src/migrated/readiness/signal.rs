#[derive(Clone, Debug, Default, PartialEq)]
pub struct OwnershipTransfer {
    pub scope: String,
    pub submitter: String,
    pub target_environment: String,
    pub correlation_id: Option<String>,
}

impl OwnershipTransfer {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.scope.trim().is_empty() { return Err("scope must be non-empty"); }
        if self.submitter.trim().is_empty() { return Err("submitter must be non-empty"); }
        if self.target_environment.trim().is_empty() { return Err("target_environment must be non-empty"); }
        Ok(())
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["OwnershipTransfer"];
