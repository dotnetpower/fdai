pub const CONTINUATION_DELIVERY_STATUS: &str = "scheduled-result";
pub const TRUNCATION_MARKER: &str = "\n[truncated]";
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ScheduledContinuationDeliveryError {
    pub message: String,
}

impl ScheduledContinuationDeliveryError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for ScheduledContinuationDeliveryError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for ScheduledContinuationDeliveryError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ContinuationDeliveryUnavailableError {
    pub message: String,
}

impl ContinuationDeliveryUnavailableError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for ContinuationDeliveryUnavailableError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for ContinuationDeliveryUnavailableError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct UnsupportedContinuationChannelError {
    pub message: String,
}

impl UnsupportedContinuationChannelError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for UnsupportedContinuationChannelError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for UnsupportedContinuationChannelError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ContinuationRenderingError {
    pub message: String,
}

impl ContinuationRenderingError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for ContinuationRenderingError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for ContinuationRenderingError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ContinuationDeliveryConflictError {
    pub message: String,
}

impl ContinuationDeliveryConflictError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for ContinuationDeliveryConflictError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for ContinuationDeliveryConflictError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ContinuationPurgeIntentError {
    pub message: String,
}

impl ContinuationPurgeIntentError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for ContinuationPurgeIntentError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for ContinuationPurgeIntentError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ScheduledContinuationDeliveryCoordinator {
    pub initialized: bool,
}

impl ScheduledContinuationDeliveryCoordinator {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn submit(&self, mut anchor_id: String, mut now: String) -> Result<String, &'static str> {
        let response: String = continuation_outbound_response(String::new()).unwrap_or_else(|_| String::new());
        Ok(String::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn purge_origin(&self, mut anchor_id: String, mut now: String) -> Result<String, &'static str> {
        Err("scheduled continuation ledger purge requires a recorded deletion fence")
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn continuation_outbound_response(mut anchor: String) -> Result<String, &'static str> {
    let channel_kind: String = external_channel_kind(String::new()).unwrap_or_else(|_| String::new());
    Ok(String::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn bounded_text(mut summary: String) -> (String, bool) {
    (String::new(), false)
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn external_channel_kind(mut value: String) -> Result<String, &'static str> {
    if value.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

pub const PUBLIC_EXPORTS: &[&str] = &["CONTINUATION_DELIVERY_STATUS", "EXTERNAL_CHANNEL_KINDS", "TRUNCATION_MARKER", "ContinuationDeliveryConflictError", "ContinuationDeliveryUnavailableError", "ContinuationPurgeIntentError", "ContinuationRenderingError", "ScheduledContinuationDeliveryCoordinator", "ScheduledContinuationDeliveryError", "UnsupportedContinuationChannelError", "continuation_outbound_response"];
