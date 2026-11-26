#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ChangeSafetyEvidenceStatus {
    #[default]
    Passed,
    Unavailable,
    Stale,
    Conflict,
    Failed,
}

impl ChangeSafetyEvidenceStatus {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Passed => "passed",
            Self::Unavailable => "unavailable",
            Self::Stale => "stale",
            Self::Conflict => "conflict",
            Self::Failed => "failed",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ChangeSafetyPreAuthorityEvidence {
    pub schema_version: String,
    pub event_id: String,
    pub action_id: String,
    pub drift_status: ChangeSafetyEvidenceStatus,
    pub what_if_status: ChangeSafetyEvidenceStatus,
    pub drift_evidence_ref: Option<String>,
    pub what_if_evidence_ref: Option<String>,
    pub observed_at: String,
    pub expires_at: String,
    pub affected_count: Option<i64>,
    pub synthetic: bool,
}

impl ChangeSafetyPreAuthorityEvidence {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.schema_version.trim().is_empty() { return Err("schema_version must be non-empty"); }
        if self.event_id.trim().is_empty() { return Err("event_id must be non-empty"); }
        if self.action_id.trim().is_empty() { return Err("action_id must be non-empty"); }
        if self.observed_at.trim().is_empty() { return Err("observed_at must be non-empty"); }
        if self.expires_at.trim().is_empty() { return Err("expires_at must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ChangeSafetyPreAuthorityDecision {
    pub ready_for_risk: bool,
    pub reason: String,
    pub action: String,
    #[allow(clippy::type_complexity)]
    pub evidence: Option<Box<ChangeSafetyPreAuthorityEvidence>>,
    pub finding_preserved: bool,
}

pub trait ChangeSafetyPreAuthorityEvidenceProvider {
    fn evaluate(&self, event: String, action: String) -> String;
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub async fn evaluate_change_safety_pre_authority(mut provider: Option<String>, mut event: String, mut action: String, mut evaluated_at: String) -> Result<ChangeSafetyPreAuthorityDecision, &'static str> {
    let Some(mut provider) = provider.clone() else { return Ok(ChangeSafetyPreAuthorityDecision { ready_for_risk: false, reason: String::from("change_safety_evidence_provider_unavailable"), action: action.clone(), evidence: None, ..Default::default() }); };
    let reason: Option<String> = rejection_reason(Default::default(), event.clone(), action.clone(), evaluated_at.clone());
    if let Some(mut reason) = reason.clone() {
        return Ok(ChangeSafetyPreAuthorityDecision { ready_for_risk: false, reason: reason.clone(), action: action.clone(), ..Default::default() });
    }
    Ok(ChangeSafetyPreAuthorityDecision { ready_for_risk: true, reason: String::from("change_safety_evidence_ready"), ..Default::default() })
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn rejection_reason(mut evidence: ChangeSafetyPreAuthorityEvidence, mut event: String, mut action: String, mut evaluated_at: String) -> Option<String> {
    if evidence.synthetic {
        return Some(String::from("change_safety_evidence_synthetic"));
    }
    if (evidence.observed_at.clone()) > (evaluated_at.clone()) {
        return Some(String::from("change_safety_evidence_from_future"));
    }
    if (evidence.expires_at.clone()) < (evaluated_at.clone()) {
        return Some(String::from("change_safety_evidence_stale"));
    }
    if (!((evidence.drift_evidence_ref.clone()).is_some())) || (!((evidence.what_if_evidence_ref.clone()).is_some())) {
        return Some(String::from("change_safety_evidence_reference_missing"));
    }
    if (evidence.affected_count.clone()).is_none() {
        return Some(String::from("change_safety_what_if_count_missing"));
    }
    None
}

pub const PUBLIC_EXPORTS: &[&str] = &["ChangeSafetyEvidenceStatus", "ChangeSafetyPreAuthorityDecision", "ChangeSafetyPreAuthorityEvidence", "ChangeSafetyPreAuthorityEvidenceProvider", "evaluate_change_safety_pre_authority"];
