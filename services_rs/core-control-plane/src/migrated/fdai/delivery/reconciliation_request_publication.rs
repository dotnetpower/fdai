#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ReconciliationRequestPublishRetryableError {
    pub message: String,
}

impl ReconciliationRequestPublishRetryableError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for ReconciliationRequestPublishRetryableError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for ReconciliationRequestPublishRetryableError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ReconciliationRequestReceiptMismatchError {
    pub message: String,
}

impl ReconciliationRequestReceiptMismatchError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for ReconciliationRequestReceiptMismatchError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for ReconciliationRequestReceiptMismatchError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct EffectReconciliationRequestPublisher {
    pub initialized: bool,
}

impl EffectReconciliationRequestPublisher {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn publish(&self, mut request_id: Option<String>) -> Result<Option<String>, &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn drain_pending(&self, mut limit: i64) -> Result<Vec<String>, &'static str> {
        if !(((1_i64) <= (limit)) && ((limit) <= (1000_i64))) {
            return Err("reconciliation request drain limit MUST be in 1 1000");
        }
        let mut published: Vec<String> = Vec::<String>::new();
        Ok(published.clone())
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn require_aware(mut now: String) -> Result<(), &'static str> {
    Err("runtime_binding_required")
}

pub const PUBLIC_EXPORTS: &[&str] = &["EffectReconciliationRequestPublisher", "ReconciliationRequestPublishRetryableError", "ReconciliationRequestReceiptMismatchError"];
