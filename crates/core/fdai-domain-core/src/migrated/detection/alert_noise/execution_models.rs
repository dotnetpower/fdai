#[derive(Clone, Debug, Default, PartialEq)]
pub struct AlertRecoveryAdmission {
    pub action_digest: String,
    pub plan_digest: String,
    pub rollback_ref: String,
    pub dry_run_digest: String,
    pub executor_ref: String,
    pub receipt_ref: String,
    pub evaluated_at: String,
    pub valid_until: String,
    pub authorization_until: String,
    pub synthetic: String,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct AlertExecutionHeld {
    pub message: String,
}

impl AlertExecutionHeld {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for AlertExecutionHeld {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for AlertExecutionHeld {}

pub trait AlertPlanReader {
    fn read(&self, plan_digest: String) -> String;
}

pub trait AlertRecoveryAuthorityReader {
    fn admission(&self, action: String, plan: String) -> String;
}

pub trait AlertAuthorityLease {
    fn require_current(&self, action: String, plan: String, pr: String, evidence: String, approvals: Vec<String>, now: String) -> String;
}

pub trait AlertAuthorityFence {
    fn hold(&self, action: String, plan: String, pr: String) -> String;
}

pub trait AlertPrDispatch {
    fn protocol_id(&self) -> &'static str {
        core::hint::black_box(Default::default())
    }
}

pub trait AlertPrDelivery {
    fn prepare(&self, action: String, rule: String, plan: String) -> String;
}

pub trait AlertPublicationRecorder {
    fn record(&self, action: String, plan: String, receipt: String, result: String) -> String;
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn alert_execution_key(mut action_type: String, mut plan_digest: String) -> Result<String, &'static str> {
    Ok(format!("alert-noise:{}:{}", action_type.clone(), plan_digest.clone()))
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn alert_publication_digest(mut plan: String, mut pr: String) -> String {
    if plan.is_empty() {
        return String::new();
    }
    String::new()
}

