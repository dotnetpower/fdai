#[derive(Clone, Debug, Default, PartialEq)]
pub struct AdaptiveRelationshipProof {
    pub target_agent: String,
    pub principal_id: String,
    pub kind: String,
    pub source_revision: String,
    pub verified_at: String,
    pub expires_at: String,
    pub execution_authority: bool,
}

impl AdaptiveRelationshipProof {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.kind.as_str(), "steward" | "collaborator") { return Err("invalid kind literal"); }
        if self.execution_authority { return Err("execution_authority violated literal bool invariant"); }
        Ok(())
    }
}

impl AdaptiveRelationshipProof {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn deny_authority(mut value: String) -> Result<String, &'static str> {
        Ok(value.clone())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn time_is_bounded(&self) -> Result<AdaptiveRelationshipProof, &'static str> {
        Err("runtime_binding_required")
    }
}

