#[derive(Clone, Debug, Default, PartialEq)]
pub struct RecoveryControlResult {
    pub plan_id: String,
    pub succeeded: bool,
    pub receipts: Vec<String>,
    pub failed_action_id: Option<String>,
    pub reason: Option<String>,
}

pub trait RecoveryActionDispatcher {
    fn dispatch(&self, action: String, idempotency_key: String) -> String;
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct PreauthorizedRecoveryController {
    pub initialized: bool,
}

impl PreauthorizedRecoveryController {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn execute(&self, mut plan: String, mut target_ids: Vec<String>, mut now: String, mut destructive: bool) -> RecoveryControlResult {
        let mut receipts: Vec<String> = Vec::<String>::new();
        RecoveryControlResult { succeeded: true, receipts: receipts.clone(), ..Default::default() }
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["PreauthorizedRecoveryController", "RecoveryActionDispatcher", "RecoveryControlResult"];
