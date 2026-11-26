#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ActionRunState {
    #[default]
    Proposed,
    Verdicted,
    HilPending,
    Approved,
    Rejected,
    DenyDropped,
    Executing,
    ExecutionUnknown,
    EffectPending,
    Succeeded,
    Failed,
    RolledBack,
    RollbackRefused,
    RollbackFailed,
}

impl ActionRunState {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Proposed => "proposed",
            Self::Verdicted => "verdicted",
            Self::HilPending => "hil_pending",
            Self::Approved => "approved",
            Self::Rejected => "rejected",
            Self::DenyDropped => "deny_dropped",
            Self::Executing => "executing",
            Self::ExecutionUnknown => "execution_unknown",
            Self::EffectPending => "effect_pending",
            Self::Succeeded => "succeeded",
            Self::Failed => "failed",
            Self::RolledBack => "rolled_back",
            Self::RollbackRefused => "rollback_refused",
            Self::RollbackFailed => "rollback_failed",
        }
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["ActionRunState", "TERMINAL_ACTION_RUN_STATES"];
