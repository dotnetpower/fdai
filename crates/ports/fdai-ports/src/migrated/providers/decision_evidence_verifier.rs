#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum DecisionEvidenceAdmissionRejectionReason {
    #[default]
    EvidenceMismatch,
    NotCurrent,
    PurposeMismatch,
    ScopeMismatch,
    SourceRevisionMismatch,
}

impl DecisionEvidenceAdmissionRejectionReason {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::EvidenceMismatch => "evidence_mismatch",
            Self::NotCurrent => "not_current",
            Self::PurposeMismatch => "purpose_mismatch",
            Self::ScopeMismatch => "scope_mismatch",
            Self::SourceRevisionMismatch => "source_revision_mismatch",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct DecisionEvidenceAdmission {
    pub receipt_digest: String,
    pub verification_bundle_digest: String,
    pub evidence_digest: String,
    pub scope_digest: String,
    pub purpose_id: String,
    pub source_revision: String,
    pub verified_at: String,
    pub valid_until: String,
    pub execution_authority: bool,
    pub promotion_authority: bool,
}

impl DecisionEvidenceAdmission {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.receipt_digest.trim().is_empty() { return Err("receipt_digest must be non-empty"); }
        if self.verification_bundle_digest.trim().is_empty() { return Err("verification_bundle_digest must be non-empty"); }
        if self.evidence_digest.trim().is_empty() { return Err("evidence_digest must be non-empty"); }
        if self.scope_digest.trim().is_empty() { return Err("scope_digest must be non-empty"); }
        if self.purpose_id.trim().is_empty() { return Err("purpose_id must be non-empty"); }
        if self.source_revision.trim().is_empty() { return Err("source_revision must be non-empty"); }
        if self.verified_at.trim().is_empty() { return Err("verified_at must be non-empty"); }
        if self.valid_until.trim().is_empty() { return Err("valid_until must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct DecisionEvidenceVerifierBinding {
    pub authority_class: String,
    pub method_id: String,
    pub verifier_id: String,
    pub verifier_version: String,
    pub trust_anchor_id: String,
    pub verifier: String,
    pub valid_from: String,
    pub valid_until: String,
    pub revoked: bool,
}

impl DecisionEvidenceVerifierBinding {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.authority_class.trim().is_empty() { return Err("authority_class must be non-empty"); }
        if self.method_id.trim().is_empty() { return Err("method_id must be non-empty"); }
        if self.verifier_id.trim().is_empty() { return Err("verifier_id must be non-empty"); }
        if self.verifier_version.trim().is_empty() { return Err("verifier_version must be non-empty"); }
        if self.trust_anchor_id.trim().is_empty() { return Err("trust_anchor_id must be non-empty"); }
        if self.verifier.trim().is_empty() { return Err("verifier must be non-empty"); }
        if self.valid_from.trim().is_empty() { return Err("valid_from must be non-empty"); }
        if self.valid_until.trim().is_empty() { return Err("valid_until must be non-empty"); }
        Ok(())
    }
}

pub const DIGEST: &str = "^sha256:[a-f0-9]{64}$";
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct DecisionEvidenceVerificationError {
    pub message: String,
}

impl DecisionEvidenceVerificationError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for DecisionEvidenceVerificationError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for DecisionEvidenceVerificationError {}

impl DecisionEvidenceAdmission {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn to_mapping(&self) -> std::collections::BTreeMap<String, String> {
        std::collections::BTreeMap::from([(String::from("evidence_digest"), self.evidence_digest.clone()), (String::from("execution_authority"), String::new()), (String::from("promotion_authority"), String::new()), (String::from("purpose_id"), self.purpose_id.clone()), (String::from("receipt_digest"), self.receipt_digest.clone()), (String::from("scope_digest"), self.scope_digest.clone()), (String::from("source_revision"), self.source_revision.clone()), (String::from("valid_until"), String::new()), (String::from("verification_bundle_digest"), self.verification_bundle_digest.clone()), (String::from("verified_at"), String::new())])
    }
}

pub trait DecisionEvidenceVerifier {
    fn verify(&self, receipt: String, trust_anchor_id: String) -> String;
}

pub trait DecisionEvidenceAdmissionProvider {
    fn admit(&self, evidence_digest: String, scope_digest: String, purpose_id: String, source_revision: String) -> String;
}

impl DecisionEvidenceVerifierBinding {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn active_at(&self, mut evaluated_at: String) -> Result<bool, &'static str> {
        Ok((!(self.revoked)) && (((self.valid_from.clone()) <= (evaluated_at.clone())) && ((evaluated_at.clone()) <= (self.valid_until.clone()))))
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct DecisionEvidenceVerifierRegistry {
    pub initialized: bool,
}

impl DecisionEvidenceVerifierRegistry {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn resolve(&self, mut authority_class: String, mut method_id: String) -> Option<DecisionEvidenceVerifierBinding> {
        if !self.initialized {
            return None;
        }
        None
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn assess_decision_evidence_admission(mut admission: DecisionEvidenceAdmission, mut expected_evidence_digest: String, mut expected_scope_digest: String, mut expected_purpose_id: String, mut expected_source_revision: String, mut evaluated_at: String) -> Result<Vec<DecisionEvidenceAdmissionRejectionReason>, &'static str> {
    let mut reasons: Vec<String> = Vec::<String>::new();
    Ok(Vec::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn resolve_current_decision_evidence_admission(mut admission: DecisionEvidenceAdmission, mut expected_evidence_digest: String, mut expected_scope_digest: String, mut expected_purpose_id: String, mut expected_source_revision: String, mut evaluated_at: String) -> Result<Option<DecisionEvidenceAdmission>, &'static str> {
    let reasons: Vec<DecisionEvidenceAdmissionRejectionReason> = assess_decision_evidence_admission(admission.clone(), expected_evidence_digest.clone(), expected_scope_digest.clone(), expected_purpose_id.clone(), expected_source_revision.clone(), evaluated_at.clone()).unwrap_or_else(|_| Vec::new());
    if (reasons.clone()).is_empty() {
        return Ok(Some(admission.clone()));
    }
    Err("decision evidence admission does not match the exact decision input")
}

pub const PUBLIC_EXPORTS: &[&str] = &["DecisionEvidenceAdmission", "DecisionEvidenceAdmissionProvider", "DecisionEvidenceAdmissionRejectionReason", "DecisionEvidenceVerificationError", "DecisionEvidenceVerifier", "DecisionEvidenceVerifierBinding", "DecisionEvidenceVerifierRegistry", "assess_decision_evidence_admission", "resolve_current_decision_evidence_admission"];
