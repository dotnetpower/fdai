#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum RuleBindingMode {
    #[default]
    Shadow,
    Enforce,
}

impl RuleBindingMode {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Shadow => "shadow",
            Self::Enforce => "enforce",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct RuleRevisionBindingV2 {
    pub schema_version: String,
    pub binding_id: String,
    pub revision: String,
    pub profile_snapshot_digest: String,
    pub mode: RuleBindingMode,
    pub promotion_evidence_digest: Option<String>,
    pub binding_digest: String,
    pub approval_authority: bool,
    pub activation_authority: bool,
    pub execution_authority: bool,
}

impl RuleRevisionBindingV2 {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.schema_version.as_str(), "2.0.0") { return Err("invalid schema_version literal"); }
        if self.approval_authority { return Err("approval_authority violated literal bool invariant"); }
        if self.activation_authority { return Err("activation_authority violated literal bool invariant"); }
        if self.execution_authority { return Err("execution_authority violated literal bool invariant"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct RuleDualRevisionSlotV2 {
    pub schema_version: String,
    pub rule_id: String,
    pub enforcing: Box<RuleRevisionBindingV2>,
    pub prepared_shadow: Box<RuleRevisionBindingV2>,
    pub cohort_prepare_digest: String,
    pub acknowledgement_set_digest: String,
    pub created_at: String,
    pub slot_digest: String,
    pub activation_authority: bool,
    pub execution_authority: bool,
}

impl RuleDualRevisionSlotV2 {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.schema_version.as_str(), "2.0.0") { return Err("invalid schema_version literal"); }
        if self.activation_authority { return Err("activation_authority violated literal bool invariant"); }
        if self.execution_authority { return Err("execution_authority violated literal bool invariant"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct RuleRevisionEvaluationEvidenceV2 {
    pub schema_version: String,
    pub rule_id: String,
    pub revision_digest: String,
    pub binding_digest: String,
    pub slot_digest: String,
    pub mode: RuleBindingMode,
    pub evaluation_receipt_digest: String,
    pub execution_authority: bool,
}

impl RuleRevisionEvaluationEvidenceV2 {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.schema_version.as_str(), "2.0.0") { return Err("invalid schema_version literal"); }
        if self.execution_authority { return Err("execution_authority violated literal bool invariant"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct RuleRevisionPromotionApprovalV2 {
    pub schema_version: String,
    pub slot_digest: String,
    pub from_binding_digest: String,
    pub shadow_binding_digest: String,
    pub revision_evidence_digest: String,
    pub authority_receipt_digest: String,
    pub approval_profile_digest: String,
    pub approver_ids: Vec<String>,
    pub original_quorum: i64,
    pub effective_quorum: i64,
    pub approved_at: String,
    pub approval_digest: String,
    pub activation_authority: bool,
    pub execution_authority: bool,
}

impl RuleRevisionPromotionApprovalV2 {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.slot_digest.trim().is_empty() { return Err("slot_digest must be non-empty"); }
        if self.from_binding_digest.trim().is_empty() { return Err("from_binding_digest must be non-empty"); }
        if self.shadow_binding_digest.trim().is_empty() { return Err("shadow_binding_digest must be non-empty"); }
        if self.revision_evidence_digest.trim().is_empty() { return Err("revision_evidence_digest must be non-empty"); }
        if self.authority_receipt_digest.trim().is_empty() { return Err("authority_receipt_digest must be non-empty"); }
        if self.approval_profile_digest.trim().is_empty() { return Err("approval_profile_digest must be non-empty"); }
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
pub struct RuleBindingMoveCandidateV2 {
    pub schema_version: String,
    pub slot_digest: String,
    pub from_binding_digest: String,
    pub shadow_binding_digest: String,
    pub target_enforcing: Box<RuleRevisionBindingV2>,
    pub acknowledgement_set_digest: String,
    pub applied_replica_ids: Vec<String>,
    pub required_replica_ids: Vec<String>,
    pub revision_evidence_digest: String,
    pub promotion_approval_digest: String,
    pub commanded_at: String,
    pub command_digest: String,
    pub approval_authority: bool,
    pub activation_authority: bool,
    pub execution_authority: bool,
}

impl RuleBindingMoveCandidateV2 {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.schema_version.as_str(), "2.0.0") { return Err("invalid schema_version literal"); }
        if self.approval_authority { return Err("approval_authority violated literal bool invariant"); }
        if self.activation_authority { return Err("activation_authority violated literal bool invariant"); }
        if self.execution_authority { return Err("execution_authority violated literal bool invariant"); }
        Ok(())
    }
}

impl RuleRevisionBindingV2 {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn exact_id(mut value: String) -> Result<String, &'static str> {
        if (true) && ((value.clone()) != (value.trim().to_string())) {
            return Err("Rule revision binding id MUST be exact");
        }
        Ok(value.clone())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn canonical_binding(&self) -> Result<String, &'static str> {
        let expected: String = rule_revision_binding_digest(std::collections::BTreeMap::new());
        if (self.binding_digest.clone()) != (expected.clone()) {
            return Err("Rule revision binding digest mismatch");
        }
        Ok(String::new())
    }
}

impl RuleDualRevisionSlotV2 {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn aware_utc(mut value: String) -> Result<String, &'static str> {
        if value.is_empty() {
            return Err("missing_required_input");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn canonical_slot(&self) -> Result<String, &'static str> {
        let expected: String = rule_dual_revision_slot_digest(std::collections::BTreeMap::new());
        if (self.slot_digest.clone()) != (expected.clone()) {
            return Err("Rule dual-revision slot digest mismatch");
        }
        Ok(String::new())
    }
}

impl RuleRevisionPromotionApprovalV2 {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn exact_approvers(mut value: String) -> Result<String, &'static str> {
        if !(true) {
            return Ok(value.clone());
        }
        let mut normalized: Vec<String> = Vec::<String>::new();
        Ok(String::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn aware_utc(mut value: String) -> Result<String, &'static str> {
        if value.is_empty() {
            return Err("missing_required_input");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn canonical_approval(&self) -> Result<String, &'static str> {
        if ((self.effective_quorum) > (self.original_quorum)) || ((((self.approver_ids.clone()).len() as i64)) < (self.effective_quorum)) {
            return Err("Rule revision promotion approval quorum is incomplete");
        }
        let expected: String = rule_revision_promotion_approval_digest(std::collections::BTreeMap::new());
        if (self.approval_digest.clone()) != (expected.clone()) {
            return Err("Rule revision promotion approval digest mismatch");
        }
        Ok(String::new())
    }
}

impl RuleBindingMoveCandidateV2 {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn aware_utc(mut value: String) -> Result<String, &'static str> {
        if value.is_empty() {
            return Err("missing_required_input");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn complete_applied_set(&self) -> Result<String, &'static str> {
        let expected: String = rule_binding_move_candidate_digest(std::collections::BTreeMap::new());
        if (self.command_digest.clone()) != (expected.clone()) {
            return Err("Rule binding move candidate digest mismatch");
        }
        Ok(String::new())
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn rule_revision_binding_digest(mut values: std::collections::BTreeMap<String, String>) -> String {
    if values.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn rule_dual_revision_slot_digest(mut values: std::collections::BTreeMap<String, String>) -> String {
    if values.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn rule_binding_move_candidate_digest(mut values: std::collections::BTreeMap<String, String>) -> String {
    if values.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn rule_revision_promotion_approval_digest(mut values: std::collections::BTreeMap<String, String>) -> String {
    if values.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn json_values(mut values: String) -> Result<String, &'static str> {
    Ok(values.clone())
}

pub const PUBLIC_EXPORTS: &[&str] = &["RuleBindingMode", "RuleBindingMoveCandidateV2", "RuleDualRevisionSlotV2", "RuleRevisionBindingV2", "RuleRevisionEvaluationEvidenceV2", "RuleRevisionPromotionApprovalV2", "rule_binding_move_candidate_digest", "rule_dual_revision_slot_digest", "rule_revision_binding_digest", "rule_revision_promotion_approval_digest"];
