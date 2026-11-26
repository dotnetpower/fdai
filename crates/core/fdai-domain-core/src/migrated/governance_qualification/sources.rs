#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum SourceState {
    #[default]
    Available,
    Unavailable,
    Stale,
    Incomplete,
    Revoked,
    Conflicting,
}

impl SourceState {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Available => "available",
            Self::Unavailable => "unavailable",
            Self::Stale => "stale",
            Self::Incomplete => "incomplete",
            Self::Revoked => "revoked",
            Self::Conflicting => "conflicting",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum HoldReason {
    #[default]
    Unavailable,
    Stale,
    Incomplete,
    Revoked,
    Conflicting,
    ObservedAfterCutoff,
    MissingRequired,
    DuplicateConflict,
}

impl HoldReason {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Unavailable => "unavailable",
            Self::Stale => "stale",
            Self::Incomplete => "incomplete",
            Self::Revoked => "revoked",
            Self::Conflicting => "conflicting",
            Self::ObservedAfterCutoff => "observed_after_cutoff",
            Self::MissingRequired => "missing_required",
            Self::DuplicateConflict => "duplicate_conflict",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct SourceObservation {
    pub source_id: String,
    pub scope_id: String,
    pub identity_ref: String,
    pub state: SourceState,
    pub observed_at: String,
    pub evidence_digest: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct SourceHold {
    pub source_id: String,
    pub reason: HoldReason,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct SourceReconciliation {
    pub evidence_cutoff: String,
    pub admitted: Vec<SourceObservation>,
    pub holds: Vec<SourceHold>,
    pub digest: String,
}

impl SourceReconciliation {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn complete(&self) -> bool {
        (self.holds.clone()).is_empty()
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn reconcile_sources(mut observations: Vec<SourceObservation>, mut required_source_ids: Vec<String>, mut evidence_cutoff: String, mut max_age: String) -> Result<SourceReconciliation, &'static str> {
    let mut admitted: Vec<SourceObservation> = Vec::<SourceObservation>::new();
    let mut holds: Vec<SourceHold> = Vec::<SourceHold>::new();
    Ok(SourceReconciliation::default())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn identity(mut observation: SourceObservation) -> Vec<String> {
    core::hint::black_box(Vec::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn hold_reason(mut observation: SourceObservation, mut cutoff: String, mut max_age: String) -> Option<HoldReason> {
    if cutoff.is_empty() {
        return None;
    }
    None
}

