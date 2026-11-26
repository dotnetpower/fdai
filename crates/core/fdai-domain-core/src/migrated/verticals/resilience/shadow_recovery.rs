#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ShadowRecoveryOutcome {
    #[default]
    Completed,
    Halted,
}

impl ShadowRecoveryOutcome {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Completed => "completed",
            Self::Halted => "halted",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ShadowRecoveryResult {
    pub outcome: ShadowRecoveryOutcome,
    pub receipts: Vec<String>,
    pub halted_action: Option<String>,
    pub halt_reason: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ShadowRecoveryError {
    pub message: String,
}

impl ShadowRecoveryError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for ShadowRecoveryError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for ShadowRecoveryError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ShadowRecoveryOrchestrator {
    pub initialized: bool,
}

impl ShadowRecoveryOrchestrator {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn evaluate_failover(&self, mut plan: String, mut expected_recovery_epoch: i64, mut replay_start: String, mut replay_end: String) -> ShadowRecoveryResult {
        self.evaluate_actions(plan.clone(), Vec::new(), replay_start.clone(), replay_end.clone()).await
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::too_many_arguments)]
    pub async fn evaluate_failback(&self, mut plan: String, mut expected_recovery_epoch: i64, mut previous_recovery_epoch: i64, mut replay_start: String, mut replay_end: String, mut primary_ready: bool, mut state_reconciled: bool, mut primary_writer_active: bool, mut recovery_writer_active: bool) -> Result<ShadowRecoveryResult, &'static str> {
        if !(primary_ready) {
            return Err("failback requires a verified primary target");
        }
        if !(state_reconciled) {
            return Err("failback requires reconciled state");
        }
        if (primary_writer_active) || (!(recovery_writer_active)) {
            return Err("failback requires the recovery region to be the sole active writer");
        }
        Ok(self.evaluate_actions(plan.clone(), Vec::new(), replay_start.clone(), replay_end.clone()).await)
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn evaluate_actions(&self, mut plan: String, mut actions: Vec<String>, mut replay_start: String, mut replay_end: String) -> ShadowRecoveryResult {
        let mut receipts: Vec<String> = Vec::<String>::new();
        ShadowRecoveryResult { receipts: receipts.clone(), ..Default::default() }
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub fn validate_request(mut plan: String, mut required_state: String, mut expected_recovery_epoch: i64, mut replay_start: String, mut replay_end: String) -> Result<(), &'static str> {
        if (replay_end.clone()) < (replay_start.clone()) {
            return Err("replay_end MUST be  replay_start");
        }
        Ok(())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn receipt_halt_reason(mut request: String, mut receipt: String) -> Option<String> {
        if request.is_empty() {
            return None;
        }
        None
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["ShadowRecoveryError", "ShadowRecoveryOrchestrator", "ShadowRecoveryOutcome", "ShadowRecoveryResult"];
