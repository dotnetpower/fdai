#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum RuleRevisionReferenceKind {
    #[default]
    Active,
    Desired,
    Prepared,
    Applied,
    RollbackEligible,
    EnforcementPin,
    PromotionRecord,
}

impl RuleRevisionReferenceKind {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Active => "active",
            Self::Desired => "desired",
            Self::Prepared => "prepared",
            Self::Applied => "applied",
            Self::RollbackEligible => "rollback_eligible",
            Self::EnforcementPin => "enforcement_pin",
            Self::PromotionRecord => "promotion_record",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct RuleRevisionReferenceV2 {
    pub revision: String,
    pub kind: RuleRevisionReferenceKind,
    pub owner_digest: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct RuleRevisionRetentionSnapshotV2 {
    pub schema_version: String,
    pub revision: String,
    pub retention_epoch_revision: i64,
    pub references: Vec<RuleRevisionReferenceV2>,
    pub captured_at: String,
    pub snapshot_digest: String,
    pub approval_authority: bool,
    pub activation_authority: bool,
    pub execution_authority: bool,
}

impl RuleRevisionRetentionSnapshotV2 {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.schema_version.as_str(), "2.0.0") { return Err("invalid schema_version literal"); }
        if !(1_i64..=9223372036854775807_i64).contains(&self.retention_epoch_revision) { return Err("retention_epoch_revision out of bounds"); }
        if self.approval_authority { return Err("approval_authority violated literal bool invariant"); }
        if self.activation_authority { return Err("activation_authority violated literal bool invariant"); }
        if self.execution_authority { return Err("execution_authority violated literal bool invariant"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct RuleRevisionRetirementProposalV2 {
    pub schema_version: String,
    pub snapshot: Box<RuleRevisionRetentionSnapshotV2>,
    pub reviewed_source_revision: String,
    pub requested_by: String,
    pub requested_at: String,
    pub reason: String,
    pub proposal_digest: String,
    pub approval_authority: bool,
    pub activation_authority: bool,
    pub execution_authority: bool,
}

impl RuleRevisionRetirementProposalV2 {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.schema_version.as_str(), "2.0.0") { return Err("invalid schema_version literal"); }
        if self.approval_authority { return Err("approval_authority violated literal bool invariant"); }
        if self.activation_authority { return Err("activation_authority violated literal bool invariant"); }
        if self.execution_authority { return Err("execution_authority violated literal bool invariant"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct RuleRevisionRetirementApprovalV2 {
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

impl RuleRevisionRetirementApprovalV2 {
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
pub struct RuleRevisionRetirementCommandV2 {
    pub schema_version: String,
    pub proposal: Box<RuleRevisionRetirementProposalV2>,
    pub approval: Box<RuleRevisionRetirementApprovalV2>,
    pub commanded_at: String,
    pub command_digest: String,
    pub execution_authority: bool,
}

impl RuleRevisionRetirementCommandV2 {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.schema_version.as_str(), "2.0.0") { return Err("invalid schema_version literal"); }
        if self.execution_authority { return Err("execution_authority violated literal bool invariant"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct RuleRevisionRetirementReceiptV2 {
    pub schema_version: String,
    pub revision: String,
    pub reference_snapshot_digest: String,
    pub retirement_command_digest: String,
    pub retired_at: String,
    pub receipt_digest: String,
    pub activation_authority: bool,
    pub execution_authority: bool,
}

impl RuleRevisionRetirementReceiptV2 {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.schema_version.as_str(), "2.0.0") { return Err("invalid schema_version literal"); }
        if self.activation_authority { return Err("activation_authority violated literal bool invariant"); }
        if self.execution_authority { return Err("execution_authority violated literal bool invariant"); }
        Ok(())
    }
}

impl RuleRevisionRetentionSnapshotV2 {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn aware_utc(mut value: String) -> String {
        utc(value.clone(), String::from("Rule revision retention snapshot time")).unwrap_or_else(|_| String::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn canonical_snapshot(&self) -> Result<String, &'static str> {
        let expected: String = rule_revision_retention_snapshot_digest(std::collections::BTreeMap::new());
        if (self.snapshot_digest.clone()) != (expected.clone()) {
            return Err("Rule revision retention snapshot digest mismatch");
        }
        Ok(String::new())
    }
}

impl RuleRevisionRetirementProposalV2 {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn exact_text(mut value: String) -> Result<String, &'static str> {
        if (true) && ((value.clone()) != (value.trim().to_string())) {
            return Err("Rule revision retirement proposal text MUST be exact");
        }
        Ok(value.clone())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn aware_utc(mut value: String) -> String {
        utc(value.clone(), String::from("Rule revision retirement proposal time")).unwrap_or_else(|_| String::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn canonical_proposal(&self) -> Result<String, &'static str> {
        let expected: String = rule_revision_retirement_proposal_digest(std::collections::BTreeMap::new());
        if (self.proposal_digest.clone()) != (expected.clone()) {
            return Err("Rule revision retirement proposal digest mismatch");
        }
        Ok(String::new())
    }
}

impl RuleRevisionRetirementApprovalV2 {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn exact_requester(mut value: String) -> Result<String, &'static str> {
        if (true) && ((value.clone()) != (value.trim().to_string())) {
            return Err("Rule revision retirement requester MUST be exact");
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
        utc(value.clone(), String::from("Rule revision retirement approval time")).unwrap_or_else(|_| String::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn canonical_approval(&self) -> Result<String, &'static str> {
        if ((self.effective_quorum) > (self.original_quorum)) || ((((self.approver_ids.clone()).len() as i64)) < (self.effective_quorum)) {
            return Err("Rule revision retirement approval quorum is incomplete");
        }
        let expected: String = rule_revision_retirement_approval_digest(std::collections::BTreeMap::new());
        if (self.approval_digest.clone()) != (expected.clone()) {
            return Err("Rule revision retirement approval digest mismatch");
        }
        Ok(String::new())
    }
}

impl RuleRevisionRetirementCommandV2 {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn aware_utc(mut value: String) -> String {
        utc(value.clone(), String::from("Rule revision retirement command time")).unwrap_or_else(|_| String::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn canonical_command(&self) -> Result<String, &'static str> {
        let expected: String = rule_revision_retirement_command_digest(std::collections::BTreeMap::new());
        if (self.command_digest.clone()) != (expected.clone()) {
            return Err("Rule revision retirement command digest mismatch");
        }
        Ok(String::new())
    }
}

impl RuleRevisionRetirementReceiptV2 {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn aware_utc(mut value: String) -> String {
        utc(value.clone(), String::from("Rule revision retirement time")).unwrap_or_else(|_| String::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn canonical_receipt(&self) -> Result<String, &'static str> {
        let expected: String = rule_revision_retirement_receipt_digest(std::collections::BTreeMap::new());
        if (self.receipt_digest.clone()) != (expected.clone()) {
            return Err("Rule revision retirement receipt digest mismatch");
        }
        Ok(String::new())
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn rule_revision_retention_snapshot_digest(mut values: std::collections::BTreeMap<String, String>) -> String {
    if values.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn rule_revision_retirement_proposal_digest(mut values: std::collections::BTreeMap<String, String>) -> String {
    if values.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn rule_revision_retirement_approval_digest(mut values: std::collections::BTreeMap<String, String>) -> String {
    if values.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn rule_revision_retirement_command_digest(mut values: std::collections::BTreeMap<String, String>) -> String {
    if values.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn rule_revision_retirement_receipt_digest(mut values: std::collections::BTreeMap<String, String>) -> String {
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

pub const PUBLIC_EXPORTS: &[&str] = &["RuleRevisionReferenceKind", "RuleRevisionReferenceV2", "RuleRevisionRetentionSnapshotV2", "RuleRevisionRetirementApprovalV2", "RuleRevisionRetirementCommandV2", "RuleRevisionRetirementProposalV2", "RuleRevisionRetirementReceiptV2", "rule_revision_retention_snapshot_digest", "rule_revision_retirement_approval_digest", "rule_revision_retirement_command_digest", "rule_revision_retirement_proposal_digest", "rule_revision_retirement_receipt_digest"];
