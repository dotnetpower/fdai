#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum RuleRevisionTransitionKind {
    #[default]
    RevisionChange,
    Rollback,
}

impl RuleRevisionTransitionKind {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::RevisionChange => "revision_change",
            Self::Rollback => "rollback",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct RuleRollbackEligibilityV2 {
    pub schema_version: String,
    pub source_identity: String,
    pub source_binding: String,
    pub source_authority_pointer_digest: String,
    pub superseding_generation_digest: String,
    pub release_id: String,
    pub signed_manifest_digest: String,
    pub revision_change_command_digest: String,
    pub created_at: String,
    pub expires_at: String,
    pub eligibility_digest: String,
    pub activation_authority: bool,
    pub execution_authority: bool,
}

impl RuleRollbackEligibilityV2 {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.schema_version.as_str(), "2.0.0") { return Err("invalid schema_version literal"); }
        if self.activation_authority { return Err("activation_authority violated literal bool invariant"); }
        if self.execution_authority { return Err("execution_authority violated literal bool invariant"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct RuleRevisionChangeProposalV2 {
    pub schema_version: String,
    pub source_authority_pointer_digest: String,
    pub identity_transition: String,
    pub transition_kind: RuleRevisionTransitionKind,
    pub rollback_eligibility_digest: Option<String>,
    pub rollback_eligible_until: String,
    pub rule_id: String,
    pub binding_id: String,
    pub from_revision: String,
    pub to_revision: String,
    pub slot_digest: String,
    pub binding_move_command_digest: String,
    pub signed_manifest_digest: String,
    pub release_id: String,
    pub revision_registry_root: String,
    pub cohort_prepare_digest: String,
    pub reviewed_source_revision: String,
    pub proposed_by: String,
    pub proposed_at: String,
    pub proposal_digest: String,
    pub approval_authority: bool,
    pub activation_authority: bool,
    pub execution_authority: bool,
}

impl RuleRevisionChangeProposalV2 {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.schema_version.as_str(), "2.0.0") { return Err("invalid schema_version literal"); }
        if self.approval_authority { return Err("approval_authority violated literal bool invariant"); }
        if self.activation_authority { return Err("activation_authority violated literal bool invariant"); }
        if self.execution_authority { return Err("execution_authority violated literal bool invariant"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct RuleRevisionChangeApprovalV2 {
    pub schema_version: String,
    pub proposal_digest: String,
    pub authority_receipt_digest: String,
    pub approval_profile_digest: String,
    pub requester_id: String,
    pub approver_ids: Vec<String>,
    pub original_quorum: i64,
    pub effective_quorum: i64,
    pub approved_at: String,
    pub approval_digest: String,
    pub activation_authority: bool,
    pub execution_authority: bool,
}

impl RuleRevisionChangeApprovalV2 {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.proposal_digest.trim().is_empty() { return Err("proposal_digest must be non-empty"); }
        if self.authority_receipt_digest.trim().is_empty() { return Err("authority_receipt_digest must be non-empty"); }
        if self.approval_profile_digest.trim().is_empty() { return Err("approval_profile_digest must be non-empty"); }
        if self.requester_id.trim().is_empty() { return Err("requester_id must be non-empty"); }
        if self.approved_at.trim().is_empty() { return Err("approved_at must be non-empty"); }
        if self.approval_digest.trim().is_empty() { return Err("approval_digest must be non-empty"); }
        if !matches!(self.schema_version.as_str(), "2.0.0") { return Err("invalid schema_version literal"); }
        if !(2_i64..=10_i64).contains(&self.original_quorum) { return Err("original_quorum out of bounds"); }
        if !(1_i64..=10_i64).contains(&self.effective_quorum) { return Err("effective_quorum out of bounds"); }
        if self.activation_authority { return Err("activation_authority violated literal bool invariant"); }
        if self.execution_authority { return Err("execution_authority violated literal bool invariant"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct RuleRevisionChangeCommandV2 {
    pub schema_version: String,
    pub proposal: Box<RuleRevisionChangeProposalV2>,
    pub approval: Box<RuleRevisionChangeApprovalV2>,
    pub commanded_at: String,
    pub command_digest: String,
    pub execution_authority: bool,
}

impl RuleRevisionChangeCommandV2 {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.schema_version.as_str(), "2.0.0") { return Err("invalid schema_version literal"); }
        if self.execution_authority { return Err("execution_authority violated literal bool invariant"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct RuleBindingAuthorityPointerV2 {
    pub schema_version: String,
    pub revision: i64,
    pub binding_id: String,
    pub enforcing: String,
    pub generation_digest: String,
    pub previous_binding_digest: String,
    pub binding_move_command_digest: String,
    pub revision_change_command_digest: String,
    pub changed_at: String,
    pub pointer_digest: String,
    pub activation_authority: bool,
    pub execution_authority: bool,
}

impl RuleBindingAuthorityPointerV2 {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.schema_version.as_str(), "2.0.0") { return Err("invalid schema_version literal"); }
        if !(1_i64..=9223372036854775807_i64).contains(&self.revision) { return Err("revision out of bounds"); }
        if !self.activation_authority { return Err("activation_authority violated literal bool invariant"); }
        if self.execution_authority { return Err("execution_authority violated literal bool invariant"); }
        Ok(())
    }
}

impl RuleRollbackEligibilityV2 {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn exact_release(mut value: String) -> Result<String, &'static str> {
        if (true) && ((value.clone()) != (value.trim().to_string())) {
            return Err("Rule rollback release identity MUST be exact");
        }
        Ok(value.clone())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn aware_utc(mut value: String) -> String {
        utc(value.clone(), String::from("Rule rollback eligibility time")).unwrap_or_else(|_| String::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn canonical_eligibility(&self) -> Result<String, &'static str> {
        let expected: String = rule_rollback_eligibility_v2_digest(std::collections::BTreeMap::new());
        if (self.eligibility_digest.clone()) != (expected.clone()) {
            return Err("Rule rollback eligibility digest mismatch");
        }
        Ok(String::new())
    }
}

impl RuleRevisionChangeProposalV2 {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn exact_text(mut value: String) -> Result<String, &'static str> {
        if (true) && ((value.clone()) != (value.trim().to_string())) {
            return Err("Rule revision change proposal text MUST be exact");
        }
        Ok(value.clone())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn aware_utc(mut value: String) -> String {
        utc(value.clone(), String::from("Rule revision change proposal time")).unwrap_or_else(|_| String::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn single_explicit_revision_change(&self) -> Result<String, &'static str> {
        let expected: String = rule_revision_change_proposal_digest(std::collections::BTreeMap::new());
        if (self.proposal_digest.clone()) != (expected.clone()) {
            return Err("Rule revision change proposal digest mismatch");
        }
        Ok(String::new())
    }
}

impl RuleRevisionChangeApprovalV2 {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn exact_requester(mut value: String) -> Result<String, &'static str> {
        if (true) && ((value.clone()) != (value.trim().to_string())) {
            return Err("Rule revision change requester MUST be exact");
        }
        Ok(value.clone())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn exact_approvers(mut value: String) -> Result<String, &'static str> {
        if !(true) {
            return Ok(value.clone());
        }
        let mut normalized: Vec<String> = Vec::<String>::new();
        Ok(String::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn aware_utc(mut value: String) -> String {
        utc(value.clone(), String::from("Rule revision change approval time")).unwrap_or_else(|_| String::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn canonical_approval(&self) -> Result<String, &'static str> {
        if ((self.effective_quorum) > (self.original_quorum)) || ((((self.approver_ids.clone()).len() as i64)) < (self.effective_quorum)) {
            return Err("Rule revision change approval quorum is incomplete");
        }
        let expected: String = rule_revision_change_approval_digest(std::collections::BTreeMap::new());
        if (self.approval_digest.clone()) != (expected.clone()) {
            return Err("Rule revision change approval digest mismatch");
        }
        Ok(String::new())
    }
}

impl RuleRevisionChangeCommandV2 {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn aware_utc(mut value: String) -> String {
        utc(value.clone(), String::from("Rule revision change command time")).unwrap_or_else(|_| String::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn canonical_command(&self) -> Result<String, &'static str> {
        let expected: String = rule_revision_change_command_digest(std::collections::BTreeMap::new());
        if (self.command_digest.clone()) != (expected.clone()) {
            return Err("Rule revision change command digest mismatch");
        }
        Ok(String::new())
    }
}

impl RuleBindingAuthorityPointerV2 {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn exact_binding(mut value: String) -> Result<String, &'static str> {
        if (true) && ((value.clone()) != (value.trim().to_string())) {
            return Err("Rule binding authority id MUST be exact");
        }
        Ok(value.clone())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn aware_utc(mut value: String) -> String {
        utc(value.clone(), String::from("Rule binding authority pointer time")).unwrap_or_else(|_| String::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn canonical_pointer(&self) -> Result<String, &'static str> {
        let expected: String = rule_binding_authority_pointer_v2_digest(std::collections::BTreeMap::new());
        if (self.pointer_digest.clone()) != (expected.clone()) {
            return Err("Rule binding authority pointer digest mismatch");
        }
        Ok(String::new())
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn rule_revision_change_proposal_digest(mut values: std::collections::BTreeMap<String, String>) -> String {
    if values.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn rule_revision_change_approval_digest(mut values: std::collections::BTreeMap<String, String>) -> String {
    if values.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn rule_revision_change_command_digest(mut values: std::collections::BTreeMap<String, String>) -> String {
    if values.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn rule_binding_authority_pointer_v2_digest(mut values: std::collections::BTreeMap<String, String>) -> String {
    if values.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn rule_rollback_eligibility_v2_digest(mut values: std::collections::BTreeMap<String, String>) -> String {
    if values.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn utc(mut value: String, mut label: String) -> Result<String, &'static str> {
    if value.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn json_values(mut values: String) -> String {
    values.clone()
}

pub const PUBLIC_EXPORTS: &[&str] = &["RuleBindingAuthorityPointerV2", "RuleRevisionTransitionKind", "RuleRollbackEligibilityV2", "RuleRevisionChangeApprovalV2", "RuleRevisionChangeCommandV2", "RuleRevisionChangeProposalV2", "rule_binding_authority_pointer_v2_digest", "rule_revision_change_approval_digest", "rule_revision_change_command_digest", "rule_revision_change_proposal_digest", "rule_rollback_eligibility_v2_digest"];
