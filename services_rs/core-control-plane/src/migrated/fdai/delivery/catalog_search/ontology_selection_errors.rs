#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum SelectionFailure {
    #[default]
    RequestInvalid,
    SourceUnavailable,
    SourceScopeChanged,
    SourceDrift,
    TimeDrift,
    RegistryUnavailable,
    ModelBindingChanged,
    ContextUnavailable,
    ProposalUnavailable,
    ProposalTimeout,
    ReadTimeout,
    MembershipTimeout,
    FunctionTimeout,
    ProposalContractInvalid,
    ProposalBindingChanged,
    UnresolvedReference,
    UnsupportedConstraint,
    AmbiguousRequest,
    NoCandidateMatch,
    CitationInvalid,
    SelectionBound,
    SelectionBindingChanged,
    MembershipIncomplete,
    MembershipDenied,
    PredicateInvalid,
    AgreementMismatch,
    EvidenceInvalid,
    FunctionContractInvalid,
}

impl SelectionFailure {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::RequestInvalid => "request_invalid",
            Self::SourceUnavailable => "source_unavailable",
            Self::SourceScopeChanged => "source_scope_changed",
            Self::SourceDrift => "source_drift",
            Self::TimeDrift => "time_drift",
            Self::RegistryUnavailable => "registry_unavailable",
            Self::ModelBindingChanged => "model_binding_changed",
            Self::ContextUnavailable => "context_unavailable",
            Self::ProposalUnavailable => "proposal_unavailable",
            Self::ProposalTimeout => "proposal_timeout",
            Self::ReadTimeout => "read_timeout",
            Self::MembershipTimeout => "membership_timeout",
            Self::FunctionTimeout => "function_timeout",
            Self::ProposalContractInvalid => "proposal_contract_invalid",
            Self::ProposalBindingChanged => "proposal_binding_changed",
            Self::UnresolvedReference => "unresolved_reference",
            Self::UnsupportedConstraint => "unsupported_constraint",
            Self::AmbiguousRequest => "ambiguous_request",
            Self::NoCandidateMatch => "no_candidate_match",
            Self::CitationInvalid => "citation_invalid",
            Self::SelectionBound => "selection_bound",
            Self::SelectionBindingChanged => "selection_binding_changed",
            Self::MembershipIncomplete => "membership_incomplete",
            Self::MembershipDenied => "membership_denied",
            Self::PredicateInvalid => "predicate_or_membership_invalid",
            Self::AgreementMismatch => "agreement_mismatch",
            Self::EvidenceInvalid => "evidence_invalid",
            Self::FunctionContractInvalid => "function_contract_invalid",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct CandidateSelectionError {
    pub message: String,
}

impl CandidateSelectionError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for CandidateSelectionError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for CandidateSelectionError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct CandidateSelectionDeniedError {
    pub message: String,
}

impl CandidateSelectionDeniedError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for CandidateSelectionDeniedError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for CandidateSelectionDeniedError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct GovernedReadError {
    pub message: String,
}

impl GovernedReadError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for GovernedReadError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for GovernedReadError {}

