#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum RuleActivationSource {
    #[default]
    Installation,
    PullRequest,
    Direct,
    OfflinePackage,
}

impl RuleActivationSource {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Installation => "installation",
            Self::PullRequest => "pull_request",
            Self::Direct => "direct",
            Self::OfflinePackage => "offline_package",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum RuleActivationStatus {
    #[default]
    Applied,
    AlreadyApplied,
    Conflict,
    Rejected,
    Failed,
}

impl RuleActivationStatus {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Applied => "applied",
            Self::AlreadyApplied => "already_applied",
            Self::Conflict => "conflict",
            Self::Rejected => "rejected",
            Self::Failed => "failed",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct RuleActivationDelta {
    pub rule_id: String,
    pub enabled: bool,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct RuleActivationMember {
    pub rule_id: String,
    pub rule_version: String,
    pub rule_digest: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct RuleActivationGeneration {
    pub schema_version: String,
    pub generation_id: String,
    pub generation_digest: String,
    pub profile_id: String,
    pub profile_version: String,
    pub catalog_digest: String,
    pub members: Vec<RuleActivationMember>,
    pub created_at: String,
}

impl RuleActivationGeneration {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.schema_version.as_str(), "1.0.0") { return Err("invalid schema_version literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct RuleActivationProposal {
    pub schema_version: String,
    pub request_id: String,
    pub idempotency_key: String,
    pub expected_generation_digest: Option<String>,
    pub source: RuleActivationSource,
    pub source_ref: String,
    pub source_digest: String,
    pub requested_by: String,
    pub requested_at: String,
    pub reason: String,
    pub changes: Vec<RuleActivationDelta>,
    pub approval_authority: bool,
    pub activation_authority: bool,
    pub execution_authority: bool,
}

impl RuleActivationProposal {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.schema_version.as_str(), "1.0.0") { return Err("invalid schema_version literal"); }
        if self.approval_authority { return Err("approval_authority violated literal bool invariant"); }
        if self.activation_authority { return Err("activation_authority violated literal bool invariant"); }
        if self.execution_authority { return Err("execution_authority violated literal bool invariant"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct RuleActivationApproval {
    pub proposal_digest: String,
    pub approver_ids: Vec<String>,
    pub approved_at: String,
    pub approval_ref: String,
}

impl RuleActivationApproval {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.proposal_digest.trim().is_empty() { return Err("proposal_digest must be non-empty"); }
        if self.approved_at.trim().is_empty() { return Err("approved_at must be non-empty"); }
        if self.approval_ref.trim().is_empty() { return Err("approval_ref must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct RuleActivationCommand {
    pub schema_version: String,
    pub proposal: Box<RuleActivationProposal>,
    pub approval: Box<RuleActivationApproval>,
    pub generation: Box<RuleActivationGeneration>,
    pub commanded_at: String,
    pub activation_authority: bool,
    pub execution_authority: bool,
}

impl RuleActivationCommand {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.schema_version.as_str(), "1.0.0") { return Err("invalid schema_version literal"); }
        if self.activation_authority { return Err("activation_authority violated literal bool invariant"); }
        if self.execution_authority { return Err("execution_authority violated literal bool invariant"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct RuleActivationResult {
    pub schema_version: String,
    pub request_id: String,
    pub command_digest: String,
    pub source: RuleActivationSource,
    pub source_ref: String,
    pub requested_by: String,
    pub approver_ids: Vec<String>,
    pub reason: String,
    pub changes: Vec<RuleActivationDelta>,
    pub status: RuleActivationStatus,
    pub previous_generation_digest: Option<String>,
    pub resulting_generation_digest: Option<String>,
    pub completed_at: String,
    pub applied_by: String,
    pub readback_verified: bool,
    pub failure_reason: Option<String>,
    pub execution_authority: bool,
}

impl RuleActivationResult {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.schema_version.as_str(), "1.0.0") { return Err("invalid schema_version literal"); }
        if !matches!(self.applied_by.as_str(), "Mimir") { return Err("invalid applied_by literal"); }
        if self.execution_authority { return Err("execution_authority violated literal bool invariant"); }
        Ok(())
    }
}

pub const DIGEST_PATTERN: &str = "^[a-f0-9]{64}$";
pub const GENERATION_PATTERN: &str = "^rule-activation-[a-f0-9]{32}$";
pub const REQUEST_PATTERN: &str = "^rule-activation-request-[a-f0-9]{32}$";
impl RuleActivationDelta {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn exact_rule_id(mut value: String) -> Result<String, &'static str> {
        if (value.clone()) != (value.trim().to_string()) {
            return Err("rule_id MUST NOT contain surrounding whitespace");
        }
        Ok(value.clone())
    }
}

impl RuleActivationMember {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn exact_text(mut value: String) -> Result<String, &'static str> {
        if (value.clone()) != (value.trim().to_string()) {
            return Err("Rule activation member text MUST be exact");
        }
        Ok(value.clone())
    }
}

impl RuleActivationGeneration {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn canonical_identity(&self) -> Result<RuleActivationGeneration, &'static str> {
        if ((self.profile_id.clone()) != ((self.profile_id.clone()).trim().to_string())) || ((self.profile_version.clone()) != ((self.profile_version.clone()).trim().to_string())) {
            return Err("Rule activation profile identity MUST be exact");
        }
        let digest: String = rule_activation_generation_digest(self.profile_id.clone(), self.profile_version.clone(), self.catalog_digest.clone(), self.members.clone());
        if (self.generation_digest.clone()) != (digest.clone()) {
            return Err("Rule activation generation digest mismatch");
        }
        Ok(self.clone())
    }
}

impl RuleActivationProposal {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn request_invariants(&self) -> Result<RuleActivationProposal, &'static str> {
        let digest: String = rule_activation_proposal_digest(self.idempotency_key.clone(), self.expected_generation_digest.clone(), self.source.clone(), self.source_ref.clone(), self.source_digest.clone(), self.requested_by.clone(), self.requested_at.clone(), self.reason.clone(), self.changes.clone());
        Ok(self.clone())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn proposal_digest(&self) -> String {
        rule_activation_proposal_digest(self.idempotency_key.clone(), self.expected_generation_digest.clone(), self.source.clone(), self.source_ref.clone(), self.source_digest.clone(), self.requested_by.clone(), self.requested_at.clone(), self.reason.clone(), self.changes.clone())
    }
}

impl RuleActivationApproval {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn approval_invariants(&self) -> Result<RuleActivationApproval, &'static str> {
        if (self.approval_ref.clone()) != ((self.approval_ref.clone()).trim().to_string()) {
            return Err("Rule activation approval_ref MUST be exact");
        }
        Ok(self.clone())
    }
}

impl RuleActivationCommand {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn command_invariants(&self) -> Result<RuleActivationCommand, &'static str> {
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn command_digest(&self) -> String {
        digest(String::new())
    }
}

impl RuleActivationResult {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn result_invariants(&self) -> Result<RuleActivationResult, &'static str> {
        if (self.approver_ids.clone()).contains(&(self.requested_by.clone())) {
            return Err("Rule activation result cannot record self-approval");
        }
        Ok(self.clone())
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn rule_activation_generation_digest(mut profile_id: String, mut profile_version: String, mut catalog_digest: String, mut members: Vec<RuleActivationMember>) -> String {
    digest(String::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
#[allow(clippy::too_many_arguments)]
pub fn rule_activation_proposal_digest(mut idempotency_key: String, mut expected_generation_digest: Option<String>, mut source: RuleActivationSource, mut source_ref: String, mut source_digest: String, mut requested_by: String, mut requested_at: String, mut reason: String, mut changes: Vec<RuleActivationDelta>) -> String {
    digest(String::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn digest(mut value: String) -> String {
    if value.is_empty() {
        return String::new();
    }
    String::new()
}

pub const PUBLIC_EXPORTS: &[&str] = &["RuleActivationApproval", "RuleActivationCommand", "RuleActivationDelta", "RuleActivationGeneration", "RuleActivationMember", "RuleActivationProposal", "RuleActivationResult", "RuleActivationSource", "RuleActivationStatus", "rule_activation_generation_digest", "rule_activation_proposal_digest"];
