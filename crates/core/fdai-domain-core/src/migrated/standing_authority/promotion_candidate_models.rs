pub const CANDIDATE_QUORUM: i64 = 2;

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum CandidateStatus {
    #[default]
    Pending,
    Approved,
    Denied,
}

impl CandidateStatus {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Pending => "pending",
            Self::Approved => "approved",
            Self::Denied => "denied",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ReviewDecision {
    #[default]
    Approve,
    Reject,
}

impl ReviewDecision {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Approve => "approve",
            Self::Reject => "reject",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum CandidateTransitionKind {
    #[default]
    Create,
    Review,
    Deny,
}

impl CandidateTransitionKind {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Create => "create",
            Self::Review => "review",
            Self::Deny => "deny",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum DenialReason {
    #[default]
    Revoked,
    Expired,
    StaleFence,
    LeaseIncompatible,
    ProviderIneligible,
    MissingEvidence,
    SelfReview,
    DuplicateReview,
    ConflictingReview,
    UnauthorizedReviewer,
    MissingQuorum,
    Rejection,
    RevocationRequest,
}

impl DenialReason {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Revoked => "revoked",
            Self::Expired => "expired",
            Self::StaleFence => "stale_fence",
            Self::LeaseIncompatible => "lease_incompatible",
            Self::ProviderIneligible => "provider_ineligible",
            Self::MissingEvidence => "missing_evidence",
            Self::SelfReview => "self_review",
            Self::DuplicateReview => "duplicate_review",
            Self::ConflictingReview => "conflicting_review",
            Self::UnauthorizedReviewer => "unauthorized_reviewer",
            Self::MissingQuorum => "missing_quorum",
            Self::Rejection => "rejection",
            Self::RevocationRequest => "revocation_request",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct PromotionCandidateRecord {
    pub candidate_id: String,
    pub family_id: String,
    pub revision_id: String,
    pub fence: String,
    pub lease_contract_version: String,
    pub eligible_action_types: Vec<String>,
    pub ineligible_provider_action_types: Vec<String>,
    pub evidence_requirements: Vec<String>,
    pub source_revision_id: String,
    pub creator_principal: String,
    pub authentication_evidence_digest: String,
    pub created_at: String,
    pub required_reviewer_principals: Vec<String>,
    pub quorum_required: i64,
    pub execution_authority: bool,
    pub promotion_authority: bool,
}

impl PromotionCandidateRecord {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.execution_authority { return Err("execution_authority violated literal bool invariant"); }
        if self.promotion_authority { return Err("promotion_authority violated literal bool invariant"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CandidateReviewRecord {
    pub review_id: String,
    pub candidate_id: String,
    pub reviewer_principal: String,
    pub decision: ReviewDecision,
    pub reviewed_at: String,
    pub authentication_evidence_digest: String,
    pub evidence_digests: Vec<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CandidateRevocationRecord {
    pub revocation_id: String,
    pub candidate_id: String,
    pub revoker_principal: String,
    pub revoked_at: String,
    pub authentication_evidence_digest: String,
    pub reason: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct TerminalDenialRecord {
    pub denial_id: String,
    pub candidate_id: String,
    pub denial_reason: DenialReason,
    pub denied_at: String,
    pub detail: String,
    pub intent_digest: String,
    pub terminal_audit_digest: String,
    pub execution_authority: bool,
    pub promotion_authority: bool,
}

impl TerminalDenialRecord {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.execution_authority { return Err("execution_authority violated literal bool invariant"); }
        if self.promotion_authority { return Err("promotion_authority violated literal bool invariant"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CandidateTransition {
    pub candidate_id: String,
    pub sequence: i64,
    pub kind: CandidateTransitionKind,
    pub actor_ref: String,
    pub authentication_evidence_digest: String,
    pub occurred_at: String,
    pub intent_digest: String,
    pub previous_transition_digest: Option<String>,
    pub transition_digest: String,
    pub execution_authority: bool,
    pub promotion_authority: bool,
}

impl CandidateTransition {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.execution_authority { return Err("execution_authority violated literal bool invariant"); }
        if self.promotion_authority { return Err("promotion_authority violated literal bool invariant"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CandidateSnapshot {
    pub candidate_id: String,
    pub status: CandidateStatus,
    pub revision_id: String,
    pub fencing_generation: i64,
    pub sequence: i64,
    pub head_transition_digest: String,
    pub approvals: Vec<String>,
    pub rejections: Vec<String>,
    pub quorum_required: i64,
    pub snapshot_digest: String,
    pub execution_authority: bool,
    pub promotion_authority: bool,
}

impl CandidateSnapshot {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.execution_authority { return Err("execution_authority violated literal bool invariant"); }
        if self.promotion_authority { return Err("promotion_authority violated literal bool invariant"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct PromotionCandidateWriteResult {
    pub transition: Box<CandidateTransition>,
    pub snapshot: Box<CandidateSnapshot>,
    #[allow(clippy::type_complexity)]
    pub denial: Option<Box<TerminalDenialRecord>>,
}

pub const LEASE_CONTRACT_VERSION: &str = "a3e-lease-v1";
impl CandidateTransition {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn body(&self) -> std::collections::BTreeMap<String, String> {
        std::collections::BTreeMap::from([(String::from("candidate_id"), self.candidate_id.clone()), (String::from("sequence"), String::new()), (String::from("kind"), String::new()), (String::from("actor_ref"), self.actor_ref.clone()), (String::from("authentication_evidence_digest"), self.authentication_evidence_digest.clone()), (String::from("occurred_at"), String::new()), (String::from("intent_digest"), self.intent_digest.clone()), (String::from("previous_transition_digest"), (self.previous_transition_digest.clone()).unwrap_or_default())])
    }
}

pub trait PromotionCandidateStore {
    fn create_candidate(&self, record: PromotionCandidateRecord) -> String;
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn require_human(mut name: String, mut principal: String) -> Result<(), &'static str> {
    if ((principal.clone()).starts_with("agent:")) || ((principal.clone()).starts_with("identity:thor")) {
        return Err("name MUST be human not agentexecutor");
    }
    if !((principal.clone()).starts_with("human:")) {
        return Err("name MUST start with human:");
    }
    Ok(())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn require_canonical_distinct(mut name: String, mut values: Vec<String>) -> Result<(), &'static str> {
    if (((values.clone()).len() as i64)) != ((((values.clone()).into_iter().collect::<std::collections::BTreeSet<String>>()).len() as i64)) {
        return Err("name MUST contain distinct values");
    }
    Ok(())
}

pub const PUBLIC_EXPORTS: &[&str] = &["CANDIDATE_QUORUM", "LEASE_CONTRACT_VERSION", "CandidateReviewRecord", "CandidateRevocationRecord", "CandidateSnapshot", "CandidateStatus", "CandidateTransition", "CandidateTransitionKind", "DenialReason", "PromotionCandidateRecord", "PromotionCandidateStore", "PromotionCandidateWriteResult", "ReviewDecision", "TerminalDenialRecord"];
