#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ControlLoopOutcome {
    #[default]
    Deduped,
    AbstainedRouting,
    AbstainedT0,
    Compliant,
    Executed,
    ExecutionPending,
    ExecutionNotAttempted,
    AbstainedActionBuild,
    GovernanceObserved,
    Hil,
    Denied,
    T1ReuseLogged,
    T1Abstained,
    T2ProposedLogged,
    T2Escalated,
    T2Denied,
    T2Abstained,
    OperatorRequestLogged,
    ReadinessRemediationLogged,
    CanaryRecorded,
}

impl ControlLoopOutcome {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Deduped => "deduped",
            Self::AbstainedRouting => "abstained_routing",
            Self::AbstainedT0 => "abstained_t0",
            Self::Compliant => "compliant",
            Self::Executed => "executed",
            Self::ExecutionPending => "execution_pending",
            Self::ExecutionNotAttempted => "execution_not_attempted",
            Self::AbstainedActionBuild => "abstained_action_build",
            Self::GovernanceObserved => "governance_observed",
            Self::Hil => "hil",
            Self::Denied => "denied",
            Self::T1ReuseLogged => "t1_reuse_logged",
            Self::T1Abstained => "t1_abstained",
            Self::T2ProposedLogged => "t2_proposed_logged",
            Self::T2Escalated => "t2_escalated",
            Self::T2Denied => "t2_denied",
            Self::T2Abstained => "t2_abstained",
            Self::OperatorRequestLogged => "operator_request_logged",
            Self::ReadinessRemediationLogged => "readiness_remediation_logged",
            Self::CanaryRecorded => "canary_recorded",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ControlLoopResult {
    pub outcome: ControlLoopOutcome,
    pub tier: String,
    pub decision: String,
    pub resource_type: Option<String>,
    pub citing_rule_ids: Vec<String>,
    pub execution_results: Vec<String>,
    pub reason: Option<String>,
    pub event_id: Option<String>,
    pub change_safety_decision: Option<String>,
    pub change_safety_evidence: Vec<String>,
    pub t1_decision: Option<String>,
    pub t2_decision: Option<String>,
    pub rca_result: Option<String>,
}

pub const PUBLIC_EXPORTS: &[&str] = &["ControlLoopOutcome", "ControlLoopResult"];
