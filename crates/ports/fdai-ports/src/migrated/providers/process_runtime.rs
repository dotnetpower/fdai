use std::collections::BTreeMap;
#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ProcessStatus {
    #[default]
    Pending,
    Running,
    Waiting,
    Compensating,
    Compensated,
    Succeeded,
    Failed,
    Cancelled,
    TimedOut,
}

impl ProcessStatus {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Pending => "pending",
            Self::Running => "running",
            Self::Waiting => "waiting",
            Self::Compensating => "compensating",
            Self::Compensated => "compensated",
            Self::Succeeded => "succeeded",
            Self::Failed => "failed",
            Self::Cancelled => "cancelled",
            Self::TimedOut => "timed_out",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ProcessEventKind {
    #[default]
    ProcessCreated,
    ProcessStarted,
    StepStarted,
    ActionPreBundleCommitted,
    ActionDispatchClaimed,
    ActionDispatched,
    StepWaiting,
    EvidenceAttached,
    PlanningPhaseRecorded,
    ApprovalRequested,
    ApprovalRecorded,
    DecisionRecorded,
    ParallelBranchStarted,
    ParallelBranchCompleted,
    ParallelBranchFailed,
    StepCompleted,
    StepFailed,
    CompensationStarted,
    CompensationDispatched,
    CompensationCompleted,
    RecoveryCompleted,
    ProcessCompleted,
    ProcessFailed,
    ProcessCancellationRequested,
    ProcessCancelled,
    ProcessRetryRequested,
    ProcessTimedOut,
}

impl ProcessEventKind {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::ProcessCreated => "process.created",
            Self::ProcessStarted => "process.started",
            Self::StepStarted => "step.started",
            Self::ActionPreBundleCommitted => "action.pre-bundle-committed",
            Self::ActionDispatchClaimed => "action.dispatch-claimed",
            Self::ActionDispatched => "action.dispatched",
            Self::StepWaiting => "step.waiting",
            Self::EvidenceAttached => "evidence.attached",
            Self::PlanningPhaseRecorded => "planning.phase.recorded",
            Self::ApprovalRequested => "approval.requested",
            Self::ApprovalRecorded => "approval.recorded",
            Self::DecisionRecorded => "decision.recorded",
            Self::ParallelBranchStarted => "parallel.branch.started",
            Self::ParallelBranchCompleted => "parallel.branch.completed",
            Self::ParallelBranchFailed => "parallel.branch.failed",
            Self::StepCompleted => "step.completed",
            Self::StepFailed => "step.failed",
            Self::CompensationStarted => "compensation.started",
            Self::CompensationDispatched => "compensation.dispatched",
            Self::CompensationCompleted => "compensation.completed",
            Self::RecoveryCompleted => "recovery.completed",
            Self::ProcessCompleted => "process.completed",
            Self::ProcessFailed => "process.failed",
            Self::ProcessCancellationRequested => "process.cancellation-requested",
            Self::ProcessCancelled => "process.cancelled",
            Self::ProcessRetryRequested => "process.retry-requested",
            Self::ProcessTimedOut => "process.timed_out",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ProcessSnapshot {
    pub process_id: String,
    pub workflow_ref: String,
    pub workflow_version: String,
    pub status: ProcessStatus,
    pub current_step: String,
    pub target_resource_id: String,
    pub started_at: String,
    pub updated_at: String,
    pub correlation_id: String,
    pub revision: i64,
}

impl ProcessSnapshot {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.process_id.trim().is_empty() { return Err("process_id must be non-empty"); }
        if self.workflow_ref.trim().is_empty() { return Err("workflow_ref must be non-empty"); }
        if self.workflow_version.trim().is_empty() { return Err("workflow_version must be non-empty"); }
        if self.current_step.trim().is_empty() { return Err("current_step must be non-empty"); }
        if self.target_resource_id.trim().is_empty() { return Err("target_resource_id must be non-empty"); }
        if self.started_at.trim().is_empty() { return Err("started_at must be non-empty"); }
        if self.updated_at.trim().is_empty() { return Err("updated_at must be non-empty"); }
        if self.correlation_id.trim().is_empty() { return Err("correlation_id must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ProcessEvent {
    pub event_id: String,
    pub process_id: String,
    pub kind: ProcessEventKind,
    pub idempotency_key: String,
    pub recorded_at: String,
    pub correlation_id: String,
    pub causation_id: Option<String>,
    pub step_id: Option<String>,
    pub attempt: i64,
    pub payload: BTreeMap<String, String>,
}

impl ProcessEvent {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.event_id.trim().is_empty() { return Err("event_id must be non-empty"); }
        if self.process_id.trim().is_empty() { return Err("process_id must be non-empty"); }
        if self.idempotency_key.trim().is_empty() { return Err("idempotency_key must be non-empty"); }
        if self.recorded_at.trim().is_empty() { return Err("recorded_at must be non-empty"); }
        if self.correlation_id.trim().is_empty() { return Err("correlation_id must be non-empty"); }
        Ok(())
    }
}

pub const PROCESS_ID_PATTERN: &str = "^[A-Za-z0-9_.:-]{1,200}$";
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ProcessRuntimeError {
    pub message: String,
}

impl ProcessRuntimeError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for ProcessRuntimeError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for ProcessRuntimeError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ProcessRevisionConflictError {
    pub message: String,
}

impl ProcessRevisionConflictError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for ProcessRevisionConflictError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for ProcessRevisionConflictError {}

pub trait ProcessRuntimeStore {
    fn create(&self, snapshot: ProcessSnapshot, event: ProcessEvent) -> (ProcessSnapshot, bool);
    fn transition(&self, process_id: String, expected_revision: i64, status: ProcessStatus, current_step: String, event: ProcessEvent) -> ProcessSnapshot;
    fn get(&self, process_id: String) -> Option<ProcessSnapshot>;
    fn events(&self, process_id: String) -> Vec<ProcessEvent>;
    fn append_event(&self, event: ProcessEvent) -> bool;
    fn list(&self, workflow_ref: Option<String>, status: Option<ProcessStatus>, limit: i64) -> Vec<ProcessSnapshot>;
}

pub const PUBLIC_EXPORTS: &[&str] = &["ProcessEvent", "ProcessEventKind", "PROCESS_ID_PATTERN", "ProcessRevisionConflictError", "ProcessRuntimeError", "ProcessRuntimeStore", "ProcessSnapshot", "ProcessStatus"];
