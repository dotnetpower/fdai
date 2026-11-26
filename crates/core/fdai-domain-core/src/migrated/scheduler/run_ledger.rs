#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ScheduleDispatchStatus {
    #[default]
    Claimed,
    Published,
    Failed,
    Lost,
}

impl ScheduleDispatchStatus {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Claimed => "claimed",
            Self::Published => "published",
            Self::Failed => "failed",
            Self::Lost => "lost",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ScheduleDispatchRun {
    pub run_id: String,
    pub task_id: String,
    pub scheduled_for: String,
    pub claimed_at: String,
    pub status: ScheduleDispatchStatus,
    pub attempt: i64,
    pub completed_at: Option<String>,
    pub error_kind: Option<String>,
}

pub trait ScheduleRunLedger {
    fn claim(&self, run: ScheduleDispatchRun) -> String;
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct InMemoryScheduleRunLedger {
    pub initialized: bool,
}

impl InMemoryScheduleRunLedger {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn claim(&self, mut run: ScheduleDispatchRun) -> bool {
        if !self.initialized {
            return true;
        }
        true
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn complete(&self, mut run_id: String, mut status: ScheduleDispatchStatus, mut at: String, mut error_kind: Option<String>) -> Result<ScheduleDispatchRun, &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn list_for_task(&self, mut task_id: String) -> Vec<ScheduleDispatchRun> {
        if !self.initialized {
            return Vec::new();
        }
        Vec::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn reconcile_stale(&self, mut before: String, mut at: String) -> Vec<ScheduleDispatchRun> {
        let mut reconciled: Vec<ScheduleDispatchRun> = Vec::<ScheduleDispatchRun>::new();
        reconciled.clone()
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["InMemoryScheduleRunLedger", "ScheduleDispatchRun", "ScheduleDispatchStatus", "ScheduleRunLedger"];
