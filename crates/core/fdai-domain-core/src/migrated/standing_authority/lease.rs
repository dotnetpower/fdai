pub const LEASE_MAX_VALID_SECONDS: i64 = 3600;
pub const LEASE_MIN_VALID_SECONDS: i64 = 10;

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum LeaseOutcome {
    #[default]
    Acquired,
    RevokedBeforeCommit,
    RevokedAfterCommit,
    Expired,
    StaleGeneration,
    LeaseLoss,
    PersistenceFailure,
    IneligibleCapability,
}

impl LeaseOutcome {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Acquired => "acquired",
            Self::RevokedBeforeCommit => "revoked_before_commit",
            Self::RevokedAfterCommit => "revoked_after_commit",
            Self::Expired => "expired",
            Self::StaleGeneration => "stale_generation",
            Self::LeaseLoss => "lease_loss",
            Self::PersistenceFailure => "persistence_failure",
            Self::IneligibleCapability => "ineligible_capability",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum EffectStatus {
    #[default]
    NotCommitted,
    Committed,
    Unknown,
}

impl EffectStatus {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::NotCommitted => "not_committed",
            Self::Committed => "committed",
            Self::Unknown => "unknown",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct StandingAuthorizationLease {
    pub lease_id: String,
    pub family_id: String,
    pub revision_id: String,
    pub fencing_generation: i64,
    pub transition_digest: String,
    pub action_digest: String,
    pub target_digest: String,
    pub executor_identity: String,
    pub source_revision_id: String,
    pub acquired_at: String,
    pub valid_until: String,
    pub lease_generation: i64,
    pub execution_authority: bool,
    pub promotion_authority: bool,
}

impl StandingAuthorizationLease {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.execution_authority { return Err("execution_authority violated literal bool invariant"); }
        if self.promotion_authority { return Err("promotion_authority violated literal bool invariant"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct LeaseAcquisitionRequest {
    pub fence: String,
    pub action_digest: String,
    pub target_digest: String,
    pub executor_identity: String,
    pub source_revision_id: String,
    pub requested_at: String,
    pub valid_seconds: i64,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct LeaseAcquisitionResult {
    pub outcome: LeaseOutcome,
    #[allow(clippy::type_complexity)]
    pub lease: Option<Box<StandingAuthorizationLease>>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct LeaseCheckpoint {
    pub lease_id: String,
    pub lease_generation: i64,
    pub checked_at: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ProviderCommitFenceRequest {
    pub lease_id: String,
    pub lease_generation: i64,
    pub fence: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ProviderCommitFenceResult {
    pub allowed: bool,
    pub outcome: LeaseOutcome,
    pub execution_authority: bool,
}

impl ProviderCommitFenceResult {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.execution_authority { return Err("execution_authority violated literal bool invariant"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct TerminalLeaseRecord {
    pub lease_id: String,
    pub lease_generation: i64,
    pub revision_id: String,
    pub fencing_generation: i64,
    pub effect_status: EffectStatus,
    pub released_at: String,
}

impl StandingAuthorizationLease {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn is_expired(&self, mut now: String) -> bool {
        if now.is_empty() {
            return false;
        }
        false
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn fence(&self) -> String {
        core::hint::black_box(String::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn idempotency_body(&self) -> std::collections::BTreeMap<String, String> {
        std::collections::BTreeMap::from([(String::from("lease_id"), self.lease_id.clone()), (String::from("family_id"), self.family_id.clone()), (String::from("revision_id"), self.revision_id.clone()), (String::from("fencing_generation"), String::new()), (String::from("transition_digest"), self.transition_digest.clone()), (String::from("action_digest"), self.action_digest.clone()), (String::from("target_digest"), self.target_digest.clone()), (String::from("executor_identity"), self.executor_identity.clone()), (String::from("source_revision_id"), self.source_revision_id.clone()), (String::from("acquired_at"), String::new()), (String::from("valid_until"), String::new()), (String::from("lease_generation"), String::new()), (String::from("execution_authority"), String::new()), (String::from("promotion_authority"), String::new())])
    }
}

impl LeaseAcquisitionRequest {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn idempotency_key(&self) -> String {
        provider_idempotency_key(String::new(), self.action_digest.clone(), self.target_digest.clone())
    }
}

impl TerminalLeaseRecord {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn audit_body(&self) -> std::collections::BTreeMap<String, String> {
        std::collections::BTreeMap::from([(String::from("kind"), String::from("standing_authority.lease.terminal_release")), (String::from("lease_id"), self.lease_id.clone()), (String::from("lease_generation"), String::new()), (String::from("revision_id"), self.revision_id.clone()), (String::from("fencing_generation"), String::new()), (String::from("effect_status"), String::new()), (String::from("released_at"), String::new()), (String::from("execution_authority"), String::new()), (String::from("promotion_authority"), String::new())])
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn provider_idempotency_key(mut revision_id: String, mut action_digest: String, mut target_digest: String) -> String {
    if revision_id.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn build_acquisition_request(mut fence: String, mut action_digest: String, mut target_digest: String, mut executor_identity: String, mut source_revision_id: String, mut requested_at: String, mut valid_seconds: i64) -> LeaseAcquisitionRequest {
    LeaseAcquisitionRequest { fence: fence.clone(), action_digest: action_digest.clone(), target_digest: target_digest.clone(), executor_identity: executor_identity.clone(), source_revision_id: source_revision_id.clone(), valid_seconds: valid_seconds, ..Default::default() }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn build_provider_commit_fence_request(mut lease: StandingAuthorizationLease) -> ProviderCommitFenceRequest {
    ProviderCommitFenceRequest { lease_id: lease.lease_id.clone(), lease_generation: lease.lease_generation, ..Default::default() }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn build_terminal_record(mut lease: StandingAuthorizationLease, mut effect_status: EffectStatus, mut released_at: String) -> TerminalLeaseRecord {
    TerminalLeaseRecord { lease_id: lease.lease_id.clone(), lease_generation: lease.lease_generation, revision_id: lease.revision_id.clone(), fencing_generation: lease.fencing_generation, effect_status: effect_status.clone(), ..Default::default() }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn build_checkpoint(mut lease: StandingAuthorizationLease, mut checked_at: String) -> LeaseCheckpoint {
    LeaseCheckpoint { lease_id: lease.lease_id.clone(), lease_generation: lease.lease_generation, ..Default::default() }
}

pub const PUBLIC_EXPORTS: &[&str] = &["LEASE_MAX_VALID_SECONDS", "LEASE_MIN_VALID_SECONDS", "EffectStatus", "LeaseAcquisitionRequest", "LeaseAcquisitionResult", "LeaseCheckpoint", "LeaseOutcome", "ProviderCommitFenceRequest", "ProviderCommitFenceResult", "StandingAuthorizationLease", "TerminalLeaseRecord", "build_acquisition_request", "build_checkpoint", "build_provider_commit_fence_request", "build_terminal_record", "provider_idempotency_key"];
