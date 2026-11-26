#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum EffectEvidenceClass {
    #[default]
    AuthoritativeExternal,
    ExecutorControlled,
    ProviderDispatch,
    Synthetic,
    Stale,
    Conflicting,
    Censored,
    Incomplete,
    OutOfEnvelope,
    Missing,
}

impl EffectEvidenceClass {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::AuthoritativeExternal => "authoritative_external",
            Self::ExecutorControlled => "executor_controlled",
            Self::ProviderDispatch => "provider_dispatch",
            Self::Synthetic => "synthetic",
            Self::Stale => "stale",
            Self::Conflicting => "conflicting",
            Self::Censored => "censored",
            Self::Incomplete => "incomplete",
            Self::OutOfEnvelope => "out_of_envelope",
            Self::Missing => "missing",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum CompletionClaimRejectionReason {
    #[default]
    EvidenceIneligible,
    IdentitySeparationViolation,
    FinalityIncomplete,
    ForbiddenEffectPresent,
    WatermarkStale,
    EnvelopeViolation,
    DigestTampered,
    AttemptMismatch,
    ReceiptMismatch,
    EvidenceWindowExpired,
    DuplicateClaim,
}

impl CompletionClaimRejectionReason {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::EvidenceIneligible => "evidence_ineligible",
            Self::IdentitySeparationViolation => "identity_separation_violation",
            Self::FinalityIncomplete => "finality_incomplete",
            Self::ForbiddenEffectPresent => "forbidden_effect_present",
            Self::WatermarkStale => "watermark_stale",
            Self::EnvelopeViolation => "envelope_violation",
            Self::DigestTampered => "digest_tampered",
            Self::AttemptMismatch => "attempt_mismatch",
            Self::ReceiptMismatch => "receipt_mismatch",
            Self::EvidenceWindowExpired => "evidence_window_expired",
            Self::DuplicateClaim => "duplicate_claim",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct EffectEvidenceRecord {
    pub observer_identity: String,
    pub observer_authority_class: EffectEvidenceClass,
    pub purpose_version: String,
    pub method_version: String,
    pub event_time: String,
    pub recorded_time: String,
    pub freshness_policy_seconds: i64,
    pub completeness: bool,
    pub provenance: String,
    pub conflict_status: String,
    pub synthetic: bool,
    pub evidence_digest: String,
}

impl EffectEvidenceRecord {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.observer_identity.trim().is_empty() { return Err("observer_identity must be non-empty"); }
        if self.purpose_version.trim().is_empty() { return Err("purpose_version must be non-empty"); }
        if self.method_version.trim().is_empty() { return Err("method_version must be non-empty"); }
        if self.event_time.trim().is_empty() { return Err("event_time must be non-empty"); }
        if self.recorded_time.trim().is_empty() { return Err("recorded_time must be non-empty"); }
        if self.provenance.trim().is_empty() { return Err("provenance must be non-empty"); }
        if self.conflict_status.trim().is_empty() { return Err("conflict_status must be non-empty"); }
        if self.evidence_digest.trim().is_empty() { return Err("evidence_digest must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct FinalizedWatermark {
    pub source_id: String,
    pub watermark: String,
    pub r#final: bool,
    pub watermark_digest: String,
}

impl FinalizedWatermark {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.source_id.trim().is_empty() { return Err("source_id must be non-empty"); }
        if self.watermark.trim().is_empty() { return Err("watermark must be non-empty"); }
        if self.watermark_digest.trim().is_empty() { return Err("watermark_digest must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct EffectCompletionClaim {
    pub attempt_identity_digest: String,
    pub action_digest: String,
    pub safeguard_bundle_digest: String,
    pub provider_receipt_digest: String,
    pub target_digest: String,
    pub expected_effect_digest: String,
    pub approved_envelope_digest: String,
    pub source_revision: String,
    pub evidence_window_start: String,
    pub evidence_window_end: String,
    pub effect_evidence_digest: String,
    pub validity_start: String,
    pub validity_end: String,
    pub watermark_set_digest: String,
    pub hold_revision: i64,
    pub admission_digest: String,
    pub success: bool,
    pub generation: i64,
    pub superseded_by: Option<String>,
    pub claim_digest: String,
    pub execution_authority: bool,
}

impl EffectCompletionClaim {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.execution_authority { return Err("execution_authority violated literal bool invariant"); }
        Ok(())
    }
}

pub const DIGEST: &str = "^sha256:[a-f0-9]{64}$";
impl EffectCompletionClaim {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    #[allow(clippy::too_many_arguments)]
    pub fn create_success(mut attempt_identity_digest: String, mut action_digest: String, mut safeguard_bundle_digest: String, mut provider_receipt_digest: String, mut target_digest: String, mut expected_effect_digest: String, mut approved_envelope_digest: String, mut source_revision: String, mut evidence_window_start: String, mut evidence_window_end: String, mut effect_evidence_digest: String, mut validity_start: String, mut validity_end: String, mut watermark_set_digest: String, mut hold_revision: i64, mut admission_digest: String, mut generation: i64) -> EffectCompletionClaim {
        let fields: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("attempt_identity_digest"), attempt_identity_digest.clone()), (String::from("action_digest"), action_digest.clone()), (String::from("safeguard_bundle_digest"), safeguard_bundle_digest.clone()), (String::from("provider_receipt_digest"), provider_receipt_digest.clone()), (String::from("target_digest"), target_digest.clone()), (String::from("expected_effect_digest"), expected_effect_digest.clone()), (String::from("approved_envelope_digest"), approved_envelope_digest.clone()), (String::from("source_revision"), source_revision.clone()), (String::from("evidence_window_start"), evidence_window_start.clone()), (String::from("evidence_window_end"), evidence_window_end.clone()), (String::from("effect_evidence_digest"), effect_evidence_digest.clone()), (String::from("validity_start"), validity_start.clone()), (String::from("validity_end"), validity_end.clone()), (String::from("watermark_set_digest"), watermark_set_digest.clone()), (String::from("hold_revision"), String::new()), (String::from("admission_digest"), admission_digest.clone()), (String::from("success"), String::new()), (String::from("generation"), String::new()), (String::from("superseded_by"), String::new()), (String::from("execution_authority"), String::new()), (String::from("claim_digest"), String::new())]);
        Default::default()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    #[allow(clippy::too_many_arguments)]
    pub fn create_non_success(mut attempt_identity_digest: String, mut action_digest: String, mut safeguard_bundle_digest: String, mut provider_receipt_digest: String, mut target_digest: String, mut expected_effect_digest: String, mut approved_envelope_digest: String, mut source_revision: String, mut evidence_window_start: String, mut evidence_window_end: String, mut effect_evidence_digest: String, mut validity_start: String, mut validity_end: String, mut watermark_set_digest: String, mut hold_revision: i64, mut admission_digest: String, mut generation: i64) -> EffectCompletionClaim {
        let fields: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("attempt_identity_digest"), attempt_identity_digest.clone()), (String::from("action_digest"), action_digest.clone()), (String::from("safeguard_bundle_digest"), safeguard_bundle_digest.clone()), (String::from("provider_receipt_digest"), provider_receipt_digest.clone()), (String::from("target_digest"), target_digest.clone()), (String::from("expected_effect_digest"), expected_effect_digest.clone()), (String::from("approved_envelope_digest"), approved_envelope_digest.clone()), (String::from("source_revision"), source_revision.clone()), (String::from("evidence_window_start"), evidence_window_start.clone()), (String::from("evidence_window_end"), evidence_window_end.clone()), (String::from("effect_evidence_digest"), effect_evidence_digest.clone()), (String::from("validity_start"), validity_start.clone()), (String::from("validity_end"), validity_end.clone()), (String::from("watermark_set_digest"), watermark_set_digest.clone()), (String::from("hold_revision"), String::new()), (String::from("admission_digest"), admission_digest.clone()), (String::from("success"), String::new()), (String::from("generation"), String::new()), (String::from("superseded_by"), String::new()), (String::from("execution_authority"), String::new()), (String::from("claim_digest"), String::new())]);
        Default::default()
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn supersede_claim(mut prior: EffectCompletionClaim, mut superseding_digest: String) -> Result<EffectCompletionClaim, &'static str> {
    if (prior.superseded_by.clone()).is_some() {
        return Err("claim is already superseded");
    }
    let fields: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("attempt_identity_digest"), prior.attempt_identity_digest.clone()), (String::from("action_digest"), prior.action_digest.clone()), (String::from("safeguard_bundle_digest"), prior.safeguard_bundle_digest.clone()), (String::from("provider_receipt_digest"), prior.provider_receipt_digest.clone()), (String::from("target_digest"), prior.target_digest.clone()), (String::from("expected_effect_digest"), prior.expected_effect_digest.clone()), (String::from("approved_envelope_digest"), prior.approved_envelope_digest.clone()), (String::from("source_revision"), prior.source_revision.clone()), (String::from("evidence_window_start"), prior.evidence_window_start.clone()), (String::from("evidence_window_end"), prior.evidence_window_end.clone()), (String::from("effect_evidence_digest"), prior.effect_evidence_digest.clone()), (String::from("validity_start"), prior.validity_start.clone()), (String::from("validity_end"), prior.validity_end.clone()), (String::from("watermark_set_digest"), prior.watermark_set_digest.clone()), (String::from("hold_revision"), String::new()), (String::from("admission_digest"), prior.admission_digest.clone()), (String::from("success"), String::new()), (String::from("generation"), String::new()), (String::from("superseded_by"), superseding_digest.clone()), (String::from("execution_authority"), String::new()), (String::from("claim_digest"), String::new())]);
    Ok(EffectCompletionClaim { attempt_identity_digest: prior.attempt_identity_digest.clone(), action_digest: prior.action_digest.clone(), safeguard_bundle_digest: prior.safeguard_bundle_digest.clone(), provider_receipt_digest: prior.provider_receipt_digest.clone(), target_digest: prior.target_digest.clone(), expected_effect_digest: prior.expected_effect_digest.clone(), approved_envelope_digest: prior.approved_envelope_digest.clone(), source_revision: prior.source_revision.clone(), evidence_window_start: prior.evidence_window_start.clone(), evidence_window_end: prior.evidence_window_end.clone(), effect_evidence_digest: prior.effect_evidence_digest.clone(), validity_start: prior.validity_start.clone(), validity_end: prior.validity_end.clone(), watermark_set_digest: prior.watermark_set_digest.clone(), hold_revision: prior.hold_revision, admission_digest: prior.admission_digest.clone(), success: prior.success, generation: prior.generation, superseded_by: Some(superseding_digest.clone()), ..Default::default() })
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
#[allow(clippy::type_complexity)]
pub fn verify_effect_evidence(mut evidence: EffectEvidenceRecord, mut executor_identity: String, mut provider_identity: String) -> (bool, Vec<CompletionClaimRejectionReason>) {
    let mut reasons: Vec<String> = Vec::<String>::new();
    let normalized_observer: String = ((evidence.observer_identity.clone()).trim().to_string()).to_lowercase();
    let normalized_executor: String = (executor_identity.trim().to_string()).to_lowercase();
    let normalized_provider: String = ((provider_identity.clone()).trim().to_string()).to_lowercase();
    (false, Vec::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn is_current_success(mut claim: EffectCompletionClaim, mut now: String) -> bool {
    if !(claim.success) {
        return false;
    }
    if (claim.superseded_by.clone()).is_some() {
        return false;
    }
    true
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn completion_claim_digest(mut claim: EffectCompletionClaim) -> String {
    let fields: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("attempt_identity_digest"), claim.attempt_identity_digest.clone()), (String::from("action_digest"), claim.action_digest.clone()), (String::from("safeguard_bundle_digest"), claim.safeguard_bundle_digest.clone()), (String::from("provider_receipt_digest"), claim.provider_receipt_digest.clone()), (String::from("target_digest"), claim.target_digest.clone()), (String::from("expected_effect_digest"), claim.expected_effect_digest.clone()), (String::from("approved_envelope_digest"), claim.approved_envelope_digest.clone()), (String::from("source_revision"), claim.source_revision.clone()), (String::from("evidence_window_start"), String::new()), (String::from("evidence_window_end"), String::new()), (String::from("effect_evidence_digest"), claim.effect_evidence_digest.clone()), (String::from("validity_start"), String::new()), (String::from("validity_end"), String::new()), (String::from("watermark_set_digest"), claim.watermark_set_digest.clone()), (String::from("hold_revision"), String::new()), (String::from("admission_digest"), claim.admission_digest.clone()), (String::from("success"), String::new()), (String::from("generation"), String::new()), (String::from("superseded_by"), (claim.superseded_by.clone()).unwrap_or_default()), (String::from("execution_authority"), String::new()), (String::from("claim_digest"), String::new())]);
    String::new()
}

pub const PUBLIC_EXPORTS: &[&str] = &["CompletionClaimRejectionReason", "EffectCompletionClaim", "EffectEvidenceClass", "EffectEvidenceRecord", "FinalizedWatermark", "is_current_success", "supersede_claim", "verify_effect_evidence"];
