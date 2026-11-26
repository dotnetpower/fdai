pub const MAX_TEXT: i64 = 2000;
pub const MAX_SUMMARY: i64 = 8000;
pub const MAX_ITEMS: i64 = 64;

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum TaskWorkerStatus {
    #[default]
    Pending,
    Running,
    Succeeded,
    Abstained,
    Cancelled,
    TimedOut,
    BudgetExhausted,
    Denied,
    Failed,
}

impl TaskWorkerStatus {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Pending => "pending",
            Self::Running => "running",
            Self::Succeeded => "succeeded",
            Self::Abstained => "abstained",
            Self::Cancelled => "cancelled",
            Self::TimedOut => "timed_out",
            Self::BudgetExhausted => "budget_exhausted",
            Self::Denied => "denied",
            Self::Failed => "failed",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct TaskWorkerBudget {
    pub max_wall_seconds: f64,
    pub max_tool_calls: i64,
    pub max_tokens: i64,
    pub max_cost_microusd: i64,
    pub heartbeat_seconds: f64,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct AttenuatedCapabilities {
    pub allowed_tools: Vec<String>,
    pub denied_tools: Vec<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct TaskWorkerRequest {
    pub worker_id: String,
    pub parent_trace_ref: String,
    pub cancellation_owner: String,
    pub goal: String,
    pub evidence_refs: Vec<String>,
    pub constraints: Vec<String>,
    pub requested_tools: Vec<String>,
    pub budget: Box<TaskWorkerBudget>,
    pub created_at: String,
    pub depth: i64,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct TaskWorkerContext {
    pub goal: String,
    pub evidence_refs: Vec<String>,
    pub constraints: Vec<String>,
    pub parent_trace_ref: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct TaskWorkerUsage {
    pub tokens: i64,
    pub cost_microusd: i64,
    pub tool_calls: i64,
    pub reserved_tokens: i64,
    pub reserved_cost_microusd: i64,
    pub complete: bool,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct TaskWorkerOutput {
    pub summary: String,
    pub evidence_refs: Vec<String>,
    pub caveats: Vec<String>,
    pub usage: Box<TaskWorkerUsage>,
    pub abstained: bool,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct TaskWorkerToolResult {
    pub data: Vec<String>,
    pub evidence_refs: Vec<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct TaskWorkerResult {
    pub worker_id: String,
    pub parent_trace_ref: String,
    pub status: TaskWorkerStatus,
    pub summary: Option<String>,
    pub evidence_refs: Vec<String>,
    pub caveats: Vec<String>,
    pub usage: Box<TaskWorkerUsage>,
    pub terminal_reason: String,
    pub started_at: String,
    pub finished_at: String,
    pub trusted: bool,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct TaskWorkerSnapshot {
    pub request: Box<TaskWorkerRequest>,
    pub capabilities: Box<AttenuatedCapabilities>,
    pub status: TaskWorkerStatus,
    pub usage: Box<TaskWorkerUsage>,
    pub updated_at: String,
    pub heartbeat_at: Option<String>,
    #[allow(clippy::type_complexity)]
    pub result: Option<Box<TaskWorkerResult>>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct TaskWorkerEvent {
    pub worker_id: String,
    pub sequence: i64,
    pub kind: String,
    pub at: String,
    pub details: Vec<String>,
}

impl TaskWorkerUsage {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn within(&self, mut budget: TaskWorkerBudget) -> bool {
        (((self.tokens).saturating_add(self.reserved_tokens)) <= (budget.max_tokens)) && ((((self.cost_microusd).saturating_add(self.reserved_cost_microusd)) <= (budget.max_cost_microusd)) && ((self.tool_calls) <= (budget.max_tool_calls)))
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn to_dict(&self) -> std::collections::BTreeMap<String, String> {
        let mut result: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("tokens"), String::new()), (String::from("cost_microusd"), String::new()), (String::from("tool_calls"), String::new())]);
        result.clone()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn from_dict(mut raw: std::collections::BTreeMap<String, String>) -> Result<TaskWorkerUsage, &'static str> {
        let mut values: std::collections::BTreeSet<String> = std::collections::BTreeSet::from([]);
        Err("runtime_binding_required")
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn isolated_context(mut request: TaskWorkerRequest) -> TaskWorkerContext {
    TaskWorkerContext { goal: request.goal.clone(), evidence_refs: request.evidence_refs.clone(), constraints: request.constraints.clone(), parent_trace_ref: request.parent_trace_ref.clone(), ..Default::default() }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn bounded_id(mut name: String, mut value: String) -> Result<(), &'static str> {
    if name.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn bounded_text(mut name: String, mut value: String, mut maximum: i64) -> Result<(), &'static str> {
    if name.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn bounded_tuple(mut name: String, mut values: Vec<String>, mut maximum: i64) -> Result<(), &'static str> {
    if ((((values.clone()).len() as i64)) > (maximum)) || (((((values.clone()).into_iter().collect::<std::collections::BTreeSet<String>>()).len() as i64)) != (((values.clone()).len() as i64))) {
        return Err("name MUST contain  maximum unique values");
    }
    Ok(())
}

pub const PUBLIC_EXPORTS: &[&str] = &["TERMINAL_WORKER_STATUSES", "AttenuatedCapabilities", "TaskWorkerBudget", "TaskWorkerContext", "TaskWorkerEvent", "TaskWorkerOutput", "TaskWorkerRequest", "TaskWorkerResult", "TaskWorkerSnapshot", "TaskWorkerStatus", "TaskWorkerToolResult", "TaskWorkerUsage", "isolated_context"];
