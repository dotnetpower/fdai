pub trait TaskWorkerTool {
    fn call(&self, arguments: std::collections::BTreeMap<String, String>) -> String;
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct TaskWorkerToolDeniedError {
    pub message: String,
}

impl TaskWorkerToolDeniedError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for TaskWorkerToolDeniedError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for TaskWorkerToolDeniedError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct TaskWorkerBudgetExhaustedError {
    pub message: String,
}

impl TaskWorkerBudgetExhaustedError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for TaskWorkerBudgetExhaustedError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for TaskWorkerBudgetExhaustedError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct TaskWorkerPlanningBudgetError {
    pub message: String,
}

impl TaskWorkerPlanningBudgetError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for TaskWorkerPlanningBudgetError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for TaskWorkerPlanningBudgetError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct TaskWorkerToolGateway {
    pub initialized: bool,
}

impl TaskWorkerToolGateway {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn usage(&self) -> String {
        if !self.initialized {
            return String::new();
        }
        String::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn has_usage_checkpoint(&self) -> bool {
        self.initialized
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn reserve_planning(&mut self, mut tokens: i64, mut cost_microusd: i64) -> Result<(), &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn record_planning_usage(&mut self, mut tokens: i64, mut cost_microusd: i64) {
        if !self.initialized {
            return;
        }
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn checkpoint_usage(&self) {
        if !self.initialized {
            return;
        }
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn checkpoint(&self) {
        if !self.initialized {
            return;
        }
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn evidence_refs(&self) -> Vec<String> {
        if !self.initialized {
            return Vec::new();
        }
        Vec::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn invoke(&mut self, mut tool_name: String, mut arguments: std::collections::BTreeMap<String, String>) -> Result<String, &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["TaskWorkerBudgetExhaustedError", "TaskWorkerPlanningBudgetError", "TaskWorkerTool", "TaskWorkerToolDeniedError", "TaskWorkerToolGateway"];
