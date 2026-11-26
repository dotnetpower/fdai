#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum DirectionPromotionDecision {
    #[default]
    ApproveProposal,
    Reject,
}

impl DirectionPromotionDecision {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::ApproveProposal => "approve_proposal",
            Self::Reject => "reject",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct DirectionPromotionAssessment {
    pub comparison_receipt_digest: String,
    pub prior_generation_digest: String,
    pub aligned_generation_digest: String,
    pub regression_receipt_digests: Vec<String>,
    pub requested_by: String,
    pub reviewed_by: String,
    pub reviewed_at: String,
    pub decision: DirectionPromotionDecision,
    pub proposal_ready: bool,
    pub reason_codes: Vec<String>,
    pub rebuild_pointer: String,
    pub catalog_pr_required: bool,
    pub graph_mutation_authority: bool,
    pub migration_execution_authority: bool,
    pub assessment_digest: String,
}

impl DirectionPromotionAssessment {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.comparison_receipt_digest.trim().is_empty() { return Err("comparison_receipt_digest must be non-empty"); }
        if self.prior_generation_digest.trim().is_empty() { return Err("prior_generation_digest must be non-empty"); }
        if self.aligned_generation_digest.trim().is_empty() { return Err("aligned_generation_digest must be non-empty"); }
        if self.requested_by.trim().is_empty() { return Err("requested_by must be non-empty"); }
        if self.reviewed_by.trim().is_empty() { return Err("reviewed_by must be non-empty"); }
        if self.reviewed_at.trim().is_empty() { return Err("reviewed_at must be non-empty"); }
        if self.rebuild_pointer.trim().is_empty() { return Err("rebuild_pointer must be non-empty"); }
        if self.assessment_digest.trim().is_empty() { return Err("assessment_digest must be non-empty"); }
        if !self.catalog_pr_required { return Err("catalog_pr_required violated literal bool invariant"); }
        if self.graph_mutation_authority { return Err("graph_mutation_authority violated literal bool invariant"); }
        if self.migration_execution_authority { return Err("migration_execution_authority violated literal bool invariant"); }
        Ok(())
    }
}

impl DirectionPromotionAssessment {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn to_mapping(&self, mut include_digest: bool) -> std::collections::BTreeMap<String, String> {
        let mut value: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("aligned_generation_digest"), self.aligned_generation_digest.clone()), (String::from("catalog_pr_required"), String::new()), (String::from("comparison_receipt_digest"), self.comparison_receipt_digest.clone()), (String::from("decision"), String::new()), (String::from("graph_mutation_authority"), String::new()), (String::from("migration_execution_authority"), String::new()), (String::from("prior_generation_digest"), self.prior_generation_digest.clone()), (String::from("proposal_ready"), String::new()), (String::from("reason_codes"), String::new()), (String::from("rebuild_pointer"), String::new()), (String::from("regression_receipt_digests"), String::new()), (String::from("requested_by"), self.requested_by.clone()), (String::from("reviewed_at"), String::new()), (String::from("reviewed_by"), self.reviewed_by.clone())]);
        if include_digest {
            value.insert(String::from("assessment_digest"), self.assessment_digest.clone());
        }
        value.clone()
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn assess_direction_mapping_promotion(mut receipt: String, mut regression_receipt_digests: Vec<String>, mut requested_by: String, mut reviewed_by: String, mut reviewed_at: String, mut decision: DirectionPromotionDecision) -> Result<DirectionPromotionAssessment, &'static str> {
    let mut reasons: std::collections::BTreeSet<String> = std::collections::BTreeSet::<String>::new();
    if (((regression_receipt_digests.clone()).len() as i64)) != ((((regression_receipt_digests.clone()).into_iter().collect::<std::collections::BTreeSet<String>>()).len() as i64)) {
        return Err("regression receipts MUST be unique");
    }
    let canonical_regressions: Vec<String> = { let mut _v = regression_receipt_digests.clone(); _v.sort(); _v };
    Ok(DirectionPromotionAssessment { regression_receipt_digests: canonical_regressions.clone(), requested_by: requested_by.clone(), reviewed_by: reviewed_by.clone(), reviewed_at: reviewed_at.clone(), decision: decision.clone(), proposal_ready: (reasons.clone()).is_empty(), reason_codes: (reasons.clone()).into_iter().collect::<Vec<String>>(), ..Default::default() })
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn require_digest(mut name: String, mut value: String) -> Result<(), &'static str> {
    if name.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

pub const PUBLIC_EXPORTS: &[&str] = &["DirectionPromotionAssessment", "DirectionPromotionDecision", "assess_direction_mapping_promotion"];
