#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum RecoveryDisposition {
    #[default]
    NotRequired,
    Rejected,
    InDoubt,
    ObserverUnavailable,
    EffectUnverified,
    Completed,
    Replayed,
}

impl RecoveryDisposition {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::NotRequired => "not_required",
            Self::Rejected => "rejected",
            Self::InDoubt => "in_doubt",
            Self::ObserverUnavailable => "observer_unavailable",
            Self::EffectUnverified => "effect_unverified",
            Self::Completed => "completed",
            Self::Replayed => "replayed",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum RecoveryClaimDispatchState {
    #[default]
    Unclaimed,
    InFlight,
    Resolved,
}

impl RecoveryClaimDispatchState {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Unclaimed => "unclaimed",
            Self::InFlight => "in_flight",
            Self::Resolved => "resolved",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct RecoveryEffectClaimOutcome {
    pub claim: Option<String>,
    pub reason: String,
    pub disposition: RecoveryDisposition,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct RecoveryCoordinationResult {
    pub disposition: RecoveryDisposition,
    pub reason: Option<String>,
    pub attempt_identity_digest: Option<String>,
    pub claim_digest: Option<String>,
    pub effect_claim_digest: Option<String>,
    pub release_receipt_digest: Option<String>,
    pub completion_digest: Option<String>,
    pub execution_authority: bool,
    pub approval_authority: bool,
}

impl RecoveryCoordinationResult {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.execution_authority { return Err("execution_authority violated literal bool invariant"); }
        if self.approval_authority { return Err("approval_authority violated literal bool invariant"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct RecoveryEffectObservation {
    pub evidence: String,
    pub observer_identity: String,
    pub provider_identity: String,
    pub expected_effect_digest: String,
    pub approved_envelope_digest: String,
    pub action_digest: String,
    pub evidence_window_start: String,
    pub evidence_window_end: String,
    pub watermarks: Vec<String>,
    pub success: bool,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct RecoveryCoordinatorConfig {
    pub executor_identity: String,
    pub source_revision: String,
    pub quorum: i64,
    pub no_self_approval: bool,
    pub claim_validity: String,
    pub dispatch_lease: String,
}

impl RecoveryCoordinatorConfig {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.executor_identity.trim().is_empty() { return Err("executor_identity must be non-empty"); }
        if self.source_revision.trim().is_empty() { return Err("source_revision must be non-empty"); }
        if self.claim_validity.trim().is_empty() { return Err("claim_validity must be non-empty"); }
        if self.dispatch_lease.trim().is_empty() { return Err("dispatch_lease must be non-empty"); }
        Ok(())
    }
}

impl RecoveryCoordinationResult {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn recovery_incomplete(&self) -> bool {
        core::hint::black_box(false)
    }
}

impl RecoveryEffectObservation {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn watermark_set_digest(&self) -> String {
        core::hint::black_box(String::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn finalized(&self) -> bool {
        core::hint::black_box(false)
    }
}

pub trait RecoveryDispatchPort {
    fn dispatch_recovery(&self, attempt: String, claim: String, safeguard_bundle_digest: String, target_resource_id: String, params: std::collections::BTreeMap<String, String>, correlation_id: String) -> String;
}

pub trait RecoveryEffectObserver {
    fn observe_recovery_effect(&self, attempt: String, target_resource_id: String, provider_receipt_digest: String, observed_at: String) -> String;
}

pub trait RecoveryEffectObservationIntake {
    fn record_observation(&self, attempt: String, target_resource_id: String, provider_receipt_digest: String, observation: RecoveryEffectObservation) -> String;
}

pub trait RecoverySafeguardBundleReader {
    fn finalized_recovery_bundle_digest(&self, attempt: String, target_resource_id: String) -> String;
}

pub trait RecoveryApprovalReader {
    fn recovery_approval(&self, attempt: String, process_id: String, target_resource_id: String) -> String;
}

pub trait RecoveryApprovalRequester {
    fn request_recovery_approval(&self, attempt: String, process_id: String, target_resource_id: String, correlation_id: String) -> String;
}

pub const PUBLIC_EXPORTS: &[&str] = &["DEFAULT_CLAIM_VALIDITY", "DEFAULT_DISPATCH_LEASE", "RecoveryApprovalReader", "RecoveryApprovalRequester", "RecoveryClaimDispatchState", "RecoveryCoordinationResult", "RecoveryCoordinatorConfig", "RecoveryDispatchPort", "RecoveryDisposition", "RecoveryEffectClaimOutcome", "RecoveryEffectObservation", "RecoveryEffectObservationIntake", "RecoveryEffectObserver", "RecoverySafeguardBundleReader"];
