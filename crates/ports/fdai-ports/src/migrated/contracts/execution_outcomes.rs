use std::collections::BTreeMap;
#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum DirectApiExecutionOutcome {
    #[default]
    Dispatched,
    AlreadyApplied,
    AbstainedBlastRadius,
    AbstainedPrecondition,
    Stopped,
    Failed,
    DispatchNotAttempted,
    AwaitingEffectEvidence,
    ReceiptTimeout,
    ExecutionUnknown,
    AuthenticationFailed,
    PermissionDenied,
    PolicyDenied,
    NetworkDenied,
    RejectedMode,
    RejectedInvariant,
    RejectedCapabilityUnavailable,
    RejectedIdempotencyConflict,
    Expired,
}

impl DirectApiExecutionOutcome {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Dispatched => "dispatched",
            Self::AlreadyApplied => "already_applied",
            Self::AbstainedBlastRadius => "abstained_blast_radius",
            Self::AbstainedPrecondition => "abstained_precondition",
            Self::Stopped => "stopped",
            Self::Failed => "failed",
            Self::DispatchNotAttempted => "dispatch_not_attempted",
            Self::AwaitingEffectEvidence => "awaiting_effect_evidence",
            Self::ReceiptTimeout => "receipt_timeout",
            Self::ExecutionUnknown => "execution_unknown",
            Self::AuthenticationFailed => "authentication_failed",
            Self::PermissionDenied => "permission_denied",
            Self::PolicyDenied => "policy_denied",
            Self::NetworkDenied => "network_denied",
            Self::RejectedMode => "rejected_mode",
            Self::RejectedInvariant => "rejected_invariant",
            Self::RejectedCapabilityUnavailable => "rejected_capability_unavailable",
            Self::RejectedIdempotencyConflict => "rejected_idempotency_conflict",
            Self::Expired => "expired",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ExecutionLifecycleDisposition {
    #[default]
    Accepted,
    Pending,
    NoEffect,
    Failed,
}

impl ExecutionLifecycleDisposition {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Accepted => "accepted",
            Self::Pending => "pending",
            Self::NoEffect => "no_effect",
            Self::Failed => "failed",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct DirectApiExecutionResult {
    pub action_id: String,
    pub outcome: DirectApiExecutionOutcome,
    pub mode: String,
    pub receipt_ref: Option<String>,
    pub safeguard_bundle_digest: Option<String>,
    pub rollback_succeeded: Option<bool>,
    pub reason: Option<String>,
    pub audit_context: BTreeMap<String, String>,
}

pub const EFFECT_POSSIBLE_TERMINAL_OUTCOMES: &[&str] = &["stopped", "failed"];
#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn execution_lifecycle_disposition(mut outcome: String) -> ExecutionLifecycleDisposition {
    if outcome.is_empty() {
        return Default::default();
    }
    Default::default()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn execution_outcome_is_pending(mut outcome: String) -> bool {
    if outcome.is_empty() {
        return false;
    }
    false
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn execution_outcome_is_no_effect(mut outcome: String) -> bool {
    if outcome.is_empty() {
        return false;
    }
    false
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn execution_outcome_may_have_effect(mut outcome: String) -> bool {
    if outcome.is_empty() {
        return false;
    }
    false
}

pub const PUBLIC_EXPORTS: &[&str] = &["DirectApiExecutionOutcome", "DirectApiExecutionResult", "ExecutionLifecycleDisposition", "execution_lifecycle_disposition", "execution_outcome_is_no_effect", "execution_outcome_is_pending", "execution_outcome_may_have_effect"];
