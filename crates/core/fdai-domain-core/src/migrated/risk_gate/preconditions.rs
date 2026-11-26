#[derive(Clone, Debug, Default, PartialEq)]
pub struct PreconditionEvaluation {
    pub condition_index: i64,
    pub kind: String,
    pub satisfied: bool,
}

pub trait PreconditionEvaluator {
    fn evaluate(&self, event: String, action: String, action_type: String) -> String;
}

pub trait OpenActionEvidenceProvider {
    fn has_conflict(&self, target_ref: String, excluding_idempotency_key: String) -> String;
}

pub trait ChangeWindowEvidenceProvider {
    fn is_active(&self, target_ref: String, at: String) -> String;
}

pub trait AutomationHoldReader {
    fn is_held(&self, target_ref: String) -> String;
}

pub trait AutomationHoldRecoveryReader {
    fn recovery_eligible(&self, target_ref: String, process_id: String, step_id: String) -> String;
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct EventPreconditionEvaluator {
    pub initialized: bool,
}

impl EventPreconditionEvaluator {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn evaluate(&self, mut event: String, mut action: String, mut action_type: String) -> Vec<PreconditionEvaluation> {
        let mut evaluations: Vec<PreconditionEvaluation> = Vec::<PreconditionEvaluation>::new();
        evaluations.clone()
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct GovernedPreconditionEvaluator {
    pub initialized: bool,
}

impl GovernedPreconditionEvaluator {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn evaluate(&self, mut event: String, mut action: String, mut action_type: String) -> Vec<PreconditionEvaluation> {
        if !self.initialized {
            return Vec::new();
        }
        Vec::new()
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["AutomationHoldReader", "EventPreconditionEvaluator", "ChangeWindowEvidenceProvider", "GovernedPreconditionEvaluator", "OpenActionEvidenceProvider", "PreconditionEvaluation", "PreconditionEvaluator"];
