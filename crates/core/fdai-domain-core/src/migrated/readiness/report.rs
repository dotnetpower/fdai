#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum HandoffVerdict {
    #[default]
    Clear,
    NeedsReview,
    Blocked,
}

impl HandoffVerdict {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Clear => "clear",
            Self::NeedsReview => "needs_review",
            Self::Blocked => "blocked",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ReadinessFinding {
    pub evidence: String,
    pub severity: String,
    pub resource: String,
    pub blocking: bool,
    pub resolution: Option<String>,
    pub source: String,
    pub dimension: Option<String>,
    pub control_id: Option<String>,
    pub requirement_refs: Vec<String>,
}

impl ReadinessFinding {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.evidence.trim().is_empty() { return Err("evidence must be non-empty"); }
        if self.severity.trim().is_empty() { return Err("severity must be non-empty"); }
        if self.resource.trim().is_empty() { return Err("resource must be non-empty"); }
        if self.source.trim().is_empty() { return Err("source must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ReadinessReport {
    pub scope: String,
    pub submitter: String,
    pub target_environment: String,
    pub generated_at: String,
    pub mode: String,
    pub verdict: HandoffVerdict,
    pub findings: Vec<ReadinessFinding>,
    pub transfer_id: Option<String>,
    pub decision_evidence_receipt_digest: Option<String>,
    pub decision_evidence_verification_bundle_digest: Option<String>,
    pub decision_evidence_rejection_reasons: Vec<String>,
}

impl ReadinessReport {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.scope.trim().is_empty() { return Err("scope must be non-empty"); }
        if self.submitter.trim().is_empty() { return Err("submitter must be non-empty"); }
        if self.target_environment.trim().is_empty() { return Err("target_environment must be non-empty"); }
        if self.generated_at.trim().is_empty() { return Err("generated_at must be non-empty"); }
        if self.mode.trim().is_empty() { return Err("mode must be non-empty"); }
        Ok(())
    }
}

impl ReadinessReport {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn blocking_findings(&self) -> Vec<ReadinessFinding> {
        core::hint::black_box(Vec::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn blocks_handoff(&self) -> bool {
        core::hint::black_box(false)
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn to_dict(&self) -> std::collections::BTreeMap<String, String> {
        std::collections::BTreeMap::from([(String::from("scope"), self.scope.clone()), (String::from("submitter"), self.submitter.clone()), (String::from("target_environment"), self.target_environment.clone()), (String::from("transfer_id"), (self.transfer_id.clone()).unwrap_or_default()), (String::from("generated_at"), self.generated_at.clone()), (String::from("mode"), String::new()), (String::from("verdict"), String::new()), (String::from("blocks_handoff"), String::new()), (String::from("decision_evidence_receipt_digest"), (self.decision_evidence_receipt_digest.clone()).unwrap_or_default()), (String::from("decision_evidence_verification_bundle_digest"), (self.decision_evidence_verification_bundle_digest.clone()).unwrap_or_default()), (String::from("decision_evidence_rejection_reasons"), String::new()), (String::from("findings"), String::new())])
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["HandoffVerdict", "ReadinessFinding", "ReadinessReport"];
