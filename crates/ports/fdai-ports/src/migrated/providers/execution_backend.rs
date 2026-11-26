#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ExecutionStatus {
    #[default]
    Planned,
    Submitted,
    Running,
    Succeeded,
    Failed,
    Cancelled,
    Ambiguous,
}

impl ExecutionStatus {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Planned => "planned",
            Self::Submitted => "submitted",
            Self::Running => "running",
            Self::Succeeded => "succeeded",
            Self::Failed => "failed",
            Self::Cancelled => "cancelled",
            Self::Ambiguous => "ambiguous",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ExecutionHealthState {
    #[default]
    Healthy,
    Degraded,
    Unavailable,
}

impl ExecutionHealthState {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Healthy => "healthy",
            Self::Degraded => "degraded",
            Self::Unavailable => "unavailable",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ExecutionCleanupState {
    #[default]
    Pending,
    Completed,
    ProviderRetention,
}

impl ExecutionCleanupState {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Pending => "pending",
            Self::Completed => "completed",
            Self::ProviderRetention => "provider_retention",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ExecutionAttemptOperation {
    #[default]
    Submit,
    Status,
    Cancel,
    CollectReceipt,
    Cleanup,
}

impl ExecutionAttemptOperation {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Submit => "submit",
            Self::Status => "status",
            Self::Cancel => "cancel",
            Self::CollectReceipt => "collect_receipt",
            Self::Cleanup => "cleanup",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ExecutionOwnerTrace {
    pub event_ref: String,
    pub action_ref: String,
    pub correlation_ref: String,
    pub executor_role: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ExecutionBackendRequest {
    pub workload_id: String,
    pub idempotency_key: String,
    pub artifact_digest: String,
    pub profile_id: String,
    pub profile_version: String,
    pub owner_trace: Box<ExecutionOwnerTrace>,
    pub stop_condition: String,
    pub audit_ref: String,
    pub scope_ref: String,
    pub region: String,
    pub payload: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ExecutionBackendPlan {
    pub plan_ref: String,
    pub backend_kind: String,
    pub request: Box<ExecutionBackendRequest>,
    pub created_at: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ExecutionBackendReceipt {
    pub status: ExecutionStatus,
    pub submission_ref: String,
    pub receipt_ref: String,
    pub detail: String,
    pub already_existed: bool,
    pub output_digest: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ExecutionBackendCapabilities {
    pub backend_kind: String,
    pub supports_status: bool,
    pub supports_cancel: bool,
    pub supports_receipt: bool,
    pub supports_cleanup: bool,
    pub durable_provider_state: bool,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ExecutionBackendHealth {
    pub state: ExecutionHealthState,
    pub checked_at: String,
    pub detail: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ExecutionCleanupResult {
    pub state: ExecutionCleanupState,
    pub detail: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ExecutionAttempt {
    pub idempotency_key: String,
    pub sequence: i64,
    pub operation: ExecutionAttemptOperation,
    pub status: ExecutionStatus,
    pub detail: String,
    pub recorded_at: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ExecutionLedgerRecord {
    pub idempotency_key: String,
    pub workload_id: String,
    pub artifact_digest: String,
    pub profile_id: String,
    pub profile_version: String,
    pub backend_kind: String,
    pub owner_trace: Box<ExecutionOwnerTrace>,
    pub stop_condition: String,
    pub audit_ref: String,
    pub scope_ref: String,
    pub region: String,
    pub status: ExecutionStatus,
    pub submission_ref: Option<String>,
    pub receipt_ref: Option<String>,
    pub detail: String,
    pub cancel_requested: bool,
    pub cleanup_state: ExecutionCleanupState,
    pub created_at: String,
    pub updated_at: String,
    pub retention_until: String,
    pub revision: i64,
}

pub const IDENTIFIER: &str = "^[a-z][a-z0-9_.-]{0,127}$";
pub const DIGEST: &str = "^[0-9a-f]{64}$";
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ExecutionBackendError {
    pub message: String,
}

impl ExecutionBackendError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for ExecutionBackendError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for ExecutionBackendError {}

pub trait ExecutionBackend {
    fn plan(&self, request: ExecutionBackendRequest, profile: String) -> String;
}

pub trait ExecutionSubmissionLedger {
    fn create(&self, record: ExecutionLedgerRecord) -> String;
}

pub const PUBLIC_EXPORTS: &[&str] = &["ExecutionAttempt", "ExecutionAttemptOperation", "ExecutionBackend", "ExecutionBackendCapabilities", "ExecutionBackendError", "ExecutionBackendHealth", "ExecutionBackendPlan", "ExecutionBackendReceipt", "ExecutionBackendRequest", "ExecutionCleanupResult", "ExecutionCleanupState", "ExecutionHealthState", "ExecutionLedgerRecord", "ExecutionOwnerTrace", "ExecutionStatus", "ExecutionSubmissionLedger"];
