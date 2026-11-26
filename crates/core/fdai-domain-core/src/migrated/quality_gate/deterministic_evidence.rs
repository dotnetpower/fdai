#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum DeterministicEvidenceKind {
    #[default]
    WhatIf,
    Security,
}

impl DeterministicEvidenceKind {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::WhatIf => "what_if",
            Self::Security => "security",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum DeterministicEvidenceStatus {
    #[default]
    Passed,
    Failed,
    Unavailable,
    Conflict,
}

impl DeterministicEvidenceStatus {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Passed => "passed",
            Self::Failed => "failed",
            Self::Unavailable => "unavailable",
            Self::Conflict => "conflict",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct DeterministicVerifierEvidence {
    pub schema_version: String,
    pub kind: DeterministicEvidenceKind,
    pub status: DeterministicEvidenceStatus,
    pub candidate_digest: String,
    pub source_authority: String,
    pub producer_id: String,
    pub observed_at: String,
    pub expires_at: String,
    pub evidence_refs: Vec<String>,
    pub synthetic: bool,
    pub reason: Option<String>,
}

impl DeterministicVerifierEvidence {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.schema_version.trim().is_empty() { return Err("schema_version must be non-empty"); }
        if self.candidate_digest.trim().is_empty() { return Err("candidate_digest must be non-empty"); }
        if self.source_authority.trim().is_empty() { return Err("source_authority must be non-empty"); }
        if self.producer_id.trim().is_empty() { return Err("producer_id must be non-empty"); }
        if self.observed_at.trim().is_empty() { return Err("observed_at must be non-empty"); }
        if self.expires_at.trim().is_empty() { return Err("expires_at must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct UnavailableDeterministicEvidenceVerifier {
    pub kind: DeterministicEvidenceKind,
    pub reason: String,
}

pub trait DeterministicEvidenceVerifier {
    fn kind(&self) -> String;
}

impl UnavailableDeterministicEvidenceVerifier {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn verify(&self, mut candidate: String) -> DeterministicVerifierEvidence {
        DeterministicVerifierEvidence { schema_version: String::from("1.0.0"), kind: self.kind.clone(), candidate_digest: quality_candidate_digest(candidate.clone()), producer_id: String::from("unbound"), reason: Some(self.reason.clone()), ..Default::default() }
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn quality_candidate_digest(mut candidate: String) -> String {
    if candidate.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn expected_evidence_authority(mut kind: DeterministicEvidenceKind) -> String {
    core::hint::black_box(String::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn is_digest(mut value: String) -> bool {
    let prefix: String = String::from("sha256:");
    false
}

pub const PUBLIC_EXPORTS: &[&str] = &["DeterministicEvidenceKind", "DeterministicEvidenceStatus", "DeterministicEvidenceVerifier", "DeterministicVerifierEvidence", "UnavailableDeterministicEvidenceVerifier", "expected_evidence_authority", "quality_candidate_digest"];
