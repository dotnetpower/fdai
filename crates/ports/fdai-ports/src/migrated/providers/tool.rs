use std::collections::BTreeMap;
#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ToolCallOutcome {
    #[default]
    Succeeded,
    AlreadyApplied,
    PreconditionFailed,
    Stopped,
    Failed,
}

impl ToolCallOutcome {
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
pub struct ToolCallRequest {
    pub action_id: String,
    pub idempotency_key: String,
    pub action_type_name: String,
    pub rule_ids: Vec<String>,
    pub tool_ref: String,
    pub arguments: BTreeMap<String, String>,
    pub labels: Vec<String>,
    pub mode: String,
    pub stop_conditions: Vec<String>,
    pub metadata: BTreeMap<String, String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ToolCallReceipt {
    pub outcome: ToolCallOutcome,
    pub receipt_ref: String,
    pub already_existed: bool,
    pub rollback_succeeded: Option<bool>,
    pub detail: Option<String>,
    pub tool_id: Option<String>,
    pub transport: Option<String>,
    pub operation_class: Option<String>,
    pub queue_duration_ms: i64,
    pub execution_duration_ms: i64,
    pub cost_microusd: Option<i64>,
    pub result_count: i64,
    pub truncated: bool,
    pub cache_status: Option<String>,
    pub recorded_at: Option<String>,
    pub trace_ref: Option<String>,
}

impl ToolCallReceipt {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.receipt_ref.trim().is_empty() { return Err("receipt_ref must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ToolError {
    pub message: String,
}

impl ToolError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for ToolError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for ToolError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ToolPromotionError {
    pub message: String,
}

impl ToolPromotionError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for ToolPromotionError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for ToolPromotionError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ToolPreconditionError {
    pub message: String,
}

impl ToolPreconditionError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for ToolPreconditionError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for ToolPreconditionError {}

pub trait ToolExecutor {
    fn execute(&self, request: ToolCallRequest) -> String;
}

pub const PUBLIC_EXPORTS: &[&str] = &["ToolCallOutcome", "ToolCallReceipt", "ToolCallRequest", "ToolError", "ToolExecutor", "ToolPreconditionError", "ToolPromotionError"];
