pub const MAX_ID: i64 = 256;
pub const MAX_PROMPT: i64 = 4000;
pub const MAX_PROGRESS: i64 = 1000;
pub const MAX_COMPLETION_ATTEMPTS: i64 = 8;

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum BackgroundTaskKind {
    #[default]
    ReadOnlyInvestigation,
}

impl BackgroundTaskKind {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::ReadOnlyInvestigation => "read_only_investigation",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum BackgroundTaskStatus {
    #[default]
    Queued,
    Claimed,
    Running,
    Succeeded,
    Failed,
    Cancelled,
    TimedOut,
    Unknown,
}

impl BackgroundTaskStatus {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Queued => "queued",
            Self::Claimed => "claimed",
            Self::Running => "running",
            Self::Succeeded => "succeeded",
            Self::Failed => "failed",
            Self::Cancelled => "cancelled",
            Self::TimedOut => "timed_out",
            Self::Unknown => "unknown",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum BackgroundTaskCompletionState {
    #[default]
    Pending,
    Sending,
    Failed,
    Delivered,
    Abandoned,
}

impl BackgroundTaskCompletionState {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Pending => "pending",
            Self::Sending => "sending",
            Self::Failed => "failed",
            Self::Delivered => "delivered",
            Self::Abandoned => "abandoned",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct BackgroundTaskOrigin {
    pub conversation_id: String,
    pub channel_kind: String,
    pub channel_id: String,
    pub thread_id: Option<String>,
    pub message_id: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct BackgroundTaskBudget {
    pub max_wall_seconds: i64,
    pub max_tokens: i64,
    pub max_cost_microusd: i64,
    pub max_tool_calls: i64,
    pub max_progress_events: i64,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct BackgroundReadInvestigationSpec {
    pub intent: String,
    pub resource_name: String,
    pub scope_ref: String,
    pub lookback_seconds: i64,
    pub resource_type: Option<String>,
    pub resource_group: Option<String>,
    pub explicit_deep: bool,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct BackgroundTask {
    pub task_id: String,
    pub owner_principal_id: String,
    pub origin: Box<BackgroundTaskOrigin>,
    pub kind: BackgroundTaskKind,
    pub prompt: String,
    pub context_digest: String,
    pub capability_profile_id: String,
    pub budget: Box<BackgroundTaskBudget>,
    pub correlation_id: String,
    pub idempotency_key: String,
    pub created_at: String,
    pub retention_until: String,
    #[allow(clippy::type_complexity)]
    pub investigation: Option<Box<BackgroundReadInvestigationSpec>>,
    pub accountable_agent: Option<String>,
    pub retryable: bool,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct BackgroundTaskLease {
    pub owner: String,
    pub token: String,
    pub expires_at: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct BackgroundTaskCompletion {
    pub attempt_id: String,
    pub state: BackgroundTaskCompletionState,
    pub created_at: String,
    pub due_at: String,
    pub retention_until: String,
    pub attempt_count: i64,
    #[allow(clippy::type_complexity)]
    pub lease: Option<Box<BackgroundTaskLease>>,
    pub last_error_code: Option<String>,
    pub terminal_at: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct BackgroundTaskUsage {
    pub tokens: i64,
    pub cost_microusd: i64,
    pub tool_calls: i64,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct BackgroundTaskResult {
    pub summary: Option<String>,
    pub evidence_refs: Vec<String>,
    pub terminal_reason: String,
    pub usage: Box<BackgroundTaskUsage>,
    pub started_at: String,
    pub finished_at: String,
    pub trusted: bool,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct BackgroundTaskAttempt {
    pub attempt_id: String,
    pub task: Box<BackgroundTask>,
    pub attempt_number: i64,
    pub status: BackgroundTaskStatus,
    pub revision: i64,
    pub updated_at: String,
    #[allow(clippy::type_complexity)]
    pub lease: Option<Box<BackgroundTaskLease>>,
    pub usage: Box<BackgroundTaskUsage>,
    #[allow(clippy::type_complexity)]
    pub result: Option<Box<BackgroundTaskResult>>,
    pub parent_attempt_id: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct BackgroundTaskProgress {
    pub attempt_id: String,
    pub sequence: i64,
    pub kind: String,
    pub message: String,
    pub at: String,
    pub usage: Box<BackgroundTaskUsage>,
}

pub const BACKGROUND_TASK_ACCOUNTABLE_AGENT: &str = "Heimdall";
#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn id(mut name: String, mut value: String) -> Result<(), &'static str> {
    if name.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn text(mut name: String, mut value: String, mut maximum: i64) -> Result<(), &'static str> {
    if name.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn aware(mut name: String, mut value: String) -> Result<(), &'static str> {
    if name.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

pub const PUBLIC_EXPORTS: &[&str] = &["BACKGROUND_TASK_ACCOUNTABLE_AGENT", "MAX_COMPLETION_ATTEMPTS", "TERMINAL_BACKGROUND_STATUSES", "BackgroundTask", "BackgroundTaskAttempt", "BackgroundTaskBudget", "BackgroundTaskCompletion", "BackgroundTaskCompletionState", "BackgroundTaskKind", "BackgroundTaskLease", "BackgroundTaskOrigin", "BackgroundTaskProgress", "BackgroundTaskResult", "BackgroundTaskStatus", "BackgroundTaskUsage"];
