#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum LifecycleFenceReason {
    #[default]
    Current,
    Stale,
    StoreUnavailable,
}

impl LifecycleFenceReason {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Current => "current",
            Self::Stale => "stale",
            Self::StoreUnavailable => "store_unavailable",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct LifecycleFenceResult {
    pub current: bool,
    pub reason: LifecycleFenceReason,
    pub execution_authority: bool,
    pub promotion_authority: bool,
}

impl LifecycleFenceResult {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.execution_authority { return Err("execution_authority violated literal bool invariant"); }
        if self.promotion_authority { return Err("promotion_authority violated literal bool invariant"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct StandingAuthorizationFenceGuard {
    pub initialized: bool,
}

impl StandingAuthorizationFenceGuard {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn evaluate(&self, mut fence: String) -> LifecycleFenceResult {
        LifecycleFenceResult::default()
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["LifecycleFenceReason", "LifecycleFenceResult", "StandingAuthorizationFenceGuard"];
