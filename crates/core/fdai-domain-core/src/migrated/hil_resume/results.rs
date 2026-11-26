#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum RequestOutcome {
    #[default]
    Parked,
    ParkedDispatchFailed,
    ParkedDeferred,
    AlreadyParked,
    AlreadyOpen,
    RejectedSubject,
    ApprovalIdConflict,
    ContactConsentRequired,
    ReportLineRouteUnavailable,
    ContactDeclined,
    ContactConsentExpired,
}

impl RequestOutcome {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Parked => "parked",
            Self::ParkedDispatchFailed => "parked_dispatch_failed",
            Self::ParkedDeferred => "parked_deferred",
            Self::AlreadyParked => "already_parked",
            Self::AlreadyOpen => "already_open",
            Self::RejectedSubject => "rejected_subject",
            Self::ApprovalIdConflict => "approval_id_conflict",
            Self::ContactConsentRequired => "contact_consent_required",
            Self::ReportLineRouteUnavailable => "report_line_route_unavailable",
            Self::ContactDeclined => "contact_declined",
            Self::ContactConsentExpired => "contact_consent_expired",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ResolveOutcome {
    #[default]
    Executed,
    ExecuteFailed,
    ExecutionPending,
    ExecutionNotAttempted,
    Rejected,
    TimedOut,
    AlreadyResolved,
    NotFound,
    SelfApprovalRefused,
    OwnerSelfApprovalRequired,
    DecisionRefused,
    MissingCapability,
    ConflictingDecision,
    OwnedRouteHeld,
    ContactConsentRequired,
}

impl ResolveOutcome {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Executed => "executed",
            Self::ExecuteFailed => "execute_failed",
            Self::ExecutionPending => "execution_pending",
            Self::ExecutionNotAttempted => "execution_not_attempted",
            Self::Rejected => "rejected",
            Self::TimedOut => "timed_out",
            Self::AlreadyResolved => "already_resolved",
            Self::NotFound => "not_found",
            Self::SelfApprovalRefused => "self_approval_refused",
            Self::OwnerSelfApprovalRequired => "owner_self_approval_required",
            Self::DecisionRefused => "decision_refused",
            Self::MissingCapability => "missing_capability",
            Self::ConflictingDecision => "conflicting_decision",
            Self::OwnedRouteHeld => "owned_route_held",
            Self::ContactConsentRequired => "contact_consent_required",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct RequestApprovalResult {
    pub outcome: RequestOutcome,
    pub approval_id: String,
    pub receipt: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ResolveResult {
    pub outcome: ResolveOutcome,
    pub approval_id: String,
    pub execution_result: String,
    pub reason: Option<String>,
    pub delegated: bool,
    pub assignee_oid: Option<String>,
}

pub const PUBLIC_EXPORTS: &[&str] = &["RequestApprovalResult", "RequestOutcome", "ResolveOutcome", "ResolveResult"];
