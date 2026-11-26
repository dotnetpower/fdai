use std::collections::BTreeMap;
#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum DirectApiOutcome {
    #[default]
    Succeeded,
    AlreadyApplied,
    PreconditionFailed,
    Stopped,
    Failed,
}

impl DirectApiOutcome {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Succeeded => "succeeded",
            Self::AlreadyApplied => "already_applied",
            Self::PreconditionFailed => "precondition_failed",
            Self::Stopped => "stopped",
            Self::Failed => "failed",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct DirectApiRequest {
    pub action_id: String,
    pub idempotency_key: String,
    pub action_type_name: String,
    pub rule_ids: Vec<String>,
    pub resource_ref: String,
    pub arguments: BTreeMap<String, String>,
    pub labels: Vec<String>,
    pub mode: String,
    pub stop_conditions: Vec<String>,
    pub metadata: BTreeMap<String, String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct DirectApiReceipt {
    pub outcome: DirectApiOutcome,
    pub receipt_ref: String,
    pub already_existed: bool,
    pub rollback_succeeded: Option<bool>,
    pub detail: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct DirectApiError {
    pub message: String,
}

impl DirectApiError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for DirectApiError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for DirectApiError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct DirectApiPromotionError {
    pub message: String,
}

impl DirectApiPromotionError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for DirectApiPromotionError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for DirectApiPromotionError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct DirectApiPreconditionError {
    pub message: String,
}

impl DirectApiPreconditionError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for DirectApiPreconditionError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for DirectApiPreconditionError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct DirectApiRetryableError {
    pub message: String,
}

impl DirectApiRetryableError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for DirectApiRetryableError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for DirectApiRetryableError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct DirectApiAuthenticationError {
    pub message: String,
}

impl DirectApiAuthenticationError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for DirectApiAuthenticationError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for DirectApiAuthenticationError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct DirectApiPermissionDeniedError {
    pub message: String,
}

impl DirectApiPermissionDeniedError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for DirectApiPermissionDeniedError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for DirectApiPermissionDeniedError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct DirectApiPolicyDeniedError {
    pub message: String,
}

impl DirectApiPolicyDeniedError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for DirectApiPolicyDeniedError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for DirectApiPolicyDeniedError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct DirectApiNetworkDeniedError {
    pub message: String,
}

impl DirectApiNetworkDeniedError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for DirectApiNetworkDeniedError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for DirectApiNetworkDeniedError {}

pub trait DirectApiExecutor {
    fn execute(&self, request: DirectApiRequest) -> String;
}

pub const PUBLIC_EXPORTS: &[&str] = &["DirectApiAuthenticationError", "DirectApiError", "DirectApiNetworkDeniedError", "DirectApiPermissionDeniedError", "DirectApiPolicyDeniedError", "DirectApiExecutor", "DirectApiOutcome", "DirectApiPreconditionError", "DirectApiPromotionError", "DirectApiRetryableError", "DirectApiReceipt", "DirectApiRequest"];
