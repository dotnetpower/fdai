#[derive(Clone, Debug, Default, PartialEq)]
pub struct ReadCapabilityBinding {
    pub source_revision: String,
    pub manifest_digest: String,
    pub principal_scope_digest: String,
    pub model_binding_digest: String,
    pub data_policy_digest: String,
    pub context_protocol: String,
}

impl ReadCapabilityBinding {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.context_protocol.as_str(), "typed-selection-context-transport.v1") { return Err("invalid context_protocol literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ReadQualification {
    pub binding: Box<ReadCapabilityBinding>,
    pub outcome: String,
    pub qualification_evidence_digest: String,
    pub answer_latency_evidence_digest: String,
    pub issued_at: String,
    pub expires_at: String,
}

impl ReadQualification {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.outcome.as_str(), "qualified" | "held" | "refuted") { return Err("invalid outcome literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ReadCapabilityPointer {
    pub revision: i64,
    pub binding: Box<ReadCapabilityBinding>,
    pub qualification_digest: String,
    pub enabled: bool,
    pub approval_key: String,
    pub approval_fingerprint: String,
    pub promotion_request_digest: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ReadSelectionEvidence {
    pub binding: Box<ReadCapabilityBinding>,
    pub registry_revision: i64,
    pub qualification_digest: String,
    pub principal_ref: String,
    pub request_ref: String,
    pub query_digest: String,
    pub snapshot_digest: String,
    pub generation_digest: String,
    pub source_projection_digest: String,
    pub selection_json: String,
    pub agreement_digest: String,
    pub issued_at: String,
    pub expires_at: String,
    pub authority: String,
    pub execution_authority: bool,
}

impl ReadSelectionEvidence {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.authority.as_str(), "candidate_only") { return Err("invalid authority literal"); }
        if self.execution_authority { return Err("execution_authority violated literal bool invariant"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ReadModelStageContract {
    pub network_allowed: bool,
    pub credentials_allowed: bool,
    pub max_model_calls: i64,
    pub per_call_timeout_seconds: i64,
    pub total_timeout_seconds: i64,
    pub execution_authority: bool,
}

impl ReadModelStageContract {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !self.network_allowed { return Err("network_allowed violated literal bool invariant"); }
        if !self.credentials_allowed { return Err("credentials_allowed violated literal bool invariant"); }
        if self.execution_authority { return Err("execution_authority violated literal bool invariant"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ReadDemotionCommand {
    pub principal_scope_digest: String,
    pub expected_revision: i64,
    pub qualification_digest: String,
    pub action_run_identity: String,
    pub source_revision: String,
    pub reason: String,
    pub issued_at: String,
    pub expires_at: String,
}

impl ReadDemotionCommand {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.reason.as_str(), "revoked" | "regression" | "rollback") { return Err("invalid reason literal"); }
        Ok(())
    }
}

pub const READ_PROMOTION_ACTION: &str = "governance.promote-typed-selection-read";
pub const READ_FUNCTION: &str = "query.ontology_typed_instance_candidates";
pub const READ_QUALIFICATION_PURPOSE: &str = "typed-selection-read-qualification";
pub const READ_DEMOTION_EVENT: &str = "governance.typed-selection-read.revoked";
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ReadRecord {
    pub initialized: bool,
}

impl ReadRecord {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn digest(&self) -> String {
        if !self.initialized {
            return String::new();
        }
        String::new()
    }
}

impl ReadQualification {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn time(&self) -> Result<ReadQualification, &'static str> {
        Err("runtime_binding_required")
    }
}

impl ReadSelectionEvidence {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn time(&self) -> Result<ReadSelectionEvidence, &'static str> {
        Err("runtime_binding_required")
    }
}

impl ReadDemotionCommand {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn time(&self) -> Result<ReadDemotionCommand, &'static str> {
        Err("runtime_binding_required")
    }
}

