#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ChaosRunState {
    #[default]
    Planned,
    ImpactChecked,
    DryRunVerified,
    Approved,
    Injecting,
    Observing,
    Verified,
    StopTriggered,
    Recovering,
    Verifying,
    Recovered,
    Escalated,
    Failed,
    Denied,
}

impl ChaosRunState {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Planned => "planned",
            Self::ImpactChecked => "impact_checked",
            Self::DryRunVerified => "dry_run_verified",
            Self::Approved => "approved",
            Self::Injecting => "injecting",
            Self::Observing => "observing",
            Self::Verified => "verified",
            Self::StopTriggered => "stop_triggered",
            Self::Recovering => "recovering",
            Self::Verifying => "verifying",
            Self::Recovered => "recovered",
            Self::Escalated => "escalated",
            Self::Failed => "failed",
            Self::Denied => "denied",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ChaosRunSnapshot {
    pub run_id: String,
    pub state: ChaosRunState,
    pub revision: i64,
    pub updated_at: String,
    pub last_idempotency_key: String,
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn transition_chaos_run(mut snapshot: ChaosRunSnapshot, mut target: ChaosRunState, mut idempotency_key: String, mut at: String) -> Result<ChaosRunSnapshot, &'static str> {
    if (idempotency_key.clone()) == (snapshot.last_idempotency_key.clone()) {
        return Ok(snapshot.clone());
    }
    if (at.clone()) < (snapshot.updated_at.clone()) {
        return Err("chaos transition time MUST be monotonic");
    }
    Err("runtime_binding_required")
}

pub const PUBLIC_EXPORTS: &[&str] = &["ChaosRunSnapshot", "ChaosRunState", "transition_chaos_run"];
