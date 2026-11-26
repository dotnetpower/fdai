#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ReadInvestigationIntent {
    #[default]
    ResourceState,
    ChangeAttribution,
    ResourceChangeHistory,
    PlatformHealth,
    GuestShutdown,
    NetworkSecurity,
    NetworkPeering,
}

impl ReadInvestigationIntent {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::ResourceState => "resource_state",
            Self::ChangeAttribution => "change_attribution",
            Self::ResourceChangeHistory => "resource_change_history",
            Self::PlatformHealth => "platform_health",
            Self::GuestShutdown => "guest_shutdown",
            Self::NetworkSecurity => "network_security",
            Self::NetworkPeering => "network_peering",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ReadInvestigationOrigin {
    pub conversation_id: String,
    pub channel_kind: String,
    pub channel_id: String,
    pub thread_id: Option<String>,
    pub message_id: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ReadInvestigationSelector {
    pub name: String,
    pub resource_type: Option<String>,
    pub resource_group: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ReadInvestigationProposalBody {
    pub prompt: String,
    pub intent: ReadInvestigationIntent,
    pub resource_name: String,
    pub resource_type: Option<String>,
    pub resource_group: Option<String>,
    pub explicit_deep: bool,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ReadInvestigationTaskBudget {
    pub max_wall_seconds: i64,
    pub max_tokens: i64,
    pub max_cost_microusd: i64,
    pub max_tool_calls: i64,
    pub max_progress_events: i64,
}

impl ReadInvestigationTaskBudget {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !(1_i64..=3600_i64).contains(&self.max_wall_seconds) { return Err("max_wall_seconds out of bounds"); }
        if !(1_i64..=32768_i64).contains(&self.max_tokens) { return Err("max_tokens out of bounds"); }
        if !(0_i64..=10000000_i64).contains(&self.max_cost_microusd) { return Err("max_cost_microusd out of bounds"); }
        if !(0_i64..=100_i64).contains(&self.max_tool_calls) { return Err("max_tool_calls out of bounds"); }
        if !(1_i64..=256_i64).contains(&self.max_progress_events) { return Err("max_progress_events out of bounds"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ReadInvestigationRequest {
    pub schema_version: String,
    pub request_id: String,
    pub owner_principal_id: String,
    pub idempotency_key: String,
    pub correlation_id: String,
    pub prompt: String,
    pub intent: ReadInvestigationIntent,
    pub selector: Box<ReadInvestigationSelector>,
    pub origin: Box<ReadInvestigationOrigin>,
    pub budget: Box<ReadInvestigationTaskBudget>,
    pub explicit_deep: bool,
    pub requested_at: String,
    pub request_digest: String,
    pub accountable_agent: String,
    pub capability_profile_id: String,
    pub execution_authority: bool,
}

impl ReadInvestigationRequest {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.schema_version.as_str(), "1.0.0") { return Err("invalid schema_version literal"); }
        if !matches!(self.accountable_agent.as_str(), "Heimdall") { return Err("invalid accountable_agent literal"); }
        if !matches!(self.capability_profile_id.as_str(), "background.read-only") { return Err("invalid capability_profile_id literal"); }
        if self.execution_authority { return Err("execution_authority violated literal bool invariant"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ReadInvestigationCancellation {
    pub schema_version: String,
    pub command: String,
    pub request_id: String,
    pub owner_principal_id: String,
    pub task_id: String,
    pub idempotency_key: String,
    pub requested_at: String,
    pub admin_override: bool,
    pub request_digest: String,
    pub execution_authority: bool,
}

impl ReadInvestigationCancellation {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.schema_version.as_str(), "1.0.0") { return Err("invalid schema_version literal"); }
        if !matches!(self.command.as_str(), "cancel") { return Err("invalid command literal"); }
        if self.execution_authority { return Err("execution_authority violated literal bool invariant"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ReadInvestigationCompletionUsage {
    pub tokens: i64,
    pub cost_microusd: i64,
    pub tool_calls: i64,
}

impl ReadInvestigationCompletionUsage {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !(0_i64..=10000000_i64).contains(&self.tokens) { return Err("tokens out of bounds"); }
        if !(0_i64..=10000000_i64).contains(&self.cost_microusd) { return Err("cost_microusd out of bounds"); }
        if !(0_i64..=100_i64).contains(&self.tool_calls) { return Err("tool_calls out of bounds"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ReadInvestigationCompletion {
    pub schema_version: String,
    pub completion_id: String,
    pub task_id: String,
    pub attempt_id: String,
    pub attempt_number: i64,
    pub owner_principal_id: String,
    pub request_idempotency_key: String,
    pub correlation_id: String,
    pub origin: Box<ReadInvestigationOrigin>,
    pub status: String,
    pub terminal_reason: String,
    pub summary: Option<String>,
    pub evidence_refs: Vec<String>,
    pub usage: Box<ReadInvestigationCompletionUsage>,
    pub started_at: String,
    pub finished_at: String,
    pub completed_at: String,
    pub retention_until: String,
    pub trusted: bool,
    pub execution_authority: bool,
    pub completion_digest: String,
}

impl ReadInvestigationCompletion {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.schema_version.as_str(), "1.0.0") { return Err("invalid schema_version literal"); }
        if !(1_i64..=100_i64).contains(&self.attempt_number) { return Err("attempt_number out of bounds"); }
        if !matches!(self.status.as_str(), "succeeded" | "failed" | "cancelled" | "timed_out" | "unknown") { return Err("invalid status literal"); }
        if self.trusted { return Err("trusted violated literal bool invariant"); }
        if self.execution_authority { return Err("execution_authority violated literal bool invariant"); }
        Ok(())
    }
}

pub const READ_INVESTIGATION_REQUEST_TOPIC: &str = "operator.read-investigation.requests";
pub const READ_INVESTIGATION_CONSUMER_GROUP: &str = "core-read-investigation-v1";
pub const READ_INVESTIGATION_COMPLETION_TOPIC: &str = "core.read-investigation.completions";
pub const READ_INVESTIGATION_COMPLETION_CONSUMER_GROUP: &str = "operator-read-investigation-completion-v1";
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ReadInvestigationContract {
    pub initialized: bool,
}

impl ReadInvestigationContract {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn reject_control_characters(mut value: String) -> Result<String, &'static str> {
        Ok(value.clone())
    }
}

impl ReadInvestigationRequest {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn validate_identity(&self) -> Result<ReadInvestigationRequest, &'static str> {
        if (self.request_digest.clone()) != (read_investigation_request_digest(self.clone())) {
            return Err("read investigation request digest does not match its content");
        }
        Ok(self.clone())
    }
}

impl ReadInvestigationCancellation {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn validate_identity(&self) -> Result<ReadInvestigationCancellation, &'static str> {
        Err("runtime_binding_required")
    }
}

impl ReadInvestigationCompletion {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub fn validate_evidence_refs(mut value: Vec<String>) -> Result<Vec<String>, &'static str> {
        if ((((value.clone()).into_iter().collect::<std::collections::BTreeSet<String>>()).len() as i64)) != (((value.clone()).len() as i64)) {
            return Err("completion evidence_refs MUST be unique");
        }
        Ok(value.clone())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn validate_completion(&self) -> Result<ReadInvestigationCompletion, &'static str> {
        if (self.completion_id.clone()) != (read_investigation_completion_id(self.task_id.clone(), self.attempt_id.clone(), self.attempt_number)) {
            return Err("read investigation completion id does not match its content");
        }
        if (self.completion_digest.clone()) != (read_investigation_completion_digest(self.clone())) {
            return Err("read investigation completion digest does not match its content");
        }
        Ok(self.clone())
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn read_investigation_request_digest(mut request: ReadInvestigationRequest) -> String {
    core::hint::black_box(String::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn read_investigation_task_id(mut owner_principal_id: String, mut idempotency_key: String) -> String {
    if owner_principal_id.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn read_investigation_completion_id(mut task_id: String, mut attempt_id: String, mut attempt_number: i64) -> String {
    if task_id.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn read_investigation_completion_digest(mut completion: ReadInvestigationCompletion) -> String {
    core::hint::black_box(String::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
#[allow(clippy::too_many_arguments)]
pub fn build_read_investigation_request(mut request_id: String, mut owner_principal_id: String, mut idempotency_key: String, mut correlation_id: String, mut prompt: String, mut intent: String, mut selector: ReadInvestigationSelector, mut origin: ReadInvestigationOrigin, mut requested_at: String, mut budget: Option<ReadInvestigationTaskBudget>, mut explicit_deep: bool) -> ReadInvestigationRequest {
    let material: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("schema_version"), String::from("1.0.0")), (String::from("request_id"), request_id.clone()), (String::from("owner_principal_id"), owner_principal_id.clone()), (String::from("idempotency_key"), idempotency_key.clone()), (String::from("correlation_id"), correlation_id.clone()), (String::from("prompt"), prompt.clone()), (String::from("intent"), String::new()), (String::from("selector"), String::new()), (String::from("origin"), String::new()), (String::from("budget"), String::new()), (String::from("explicit_deep"), String::new()), (String::from("requested_at"), String::new()), (String::from("accountable_agent"), String::from("Heimdall")), (String::from("capability_profile_id"), String::from("background.read-only")), (String::from("execution_authority"), String::new())]);
    Default::default()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn build_read_investigation_cancellation(mut request_id: String, mut owner_principal_id: String, mut task_id: String, mut idempotency_key: String, mut requested_at: String, mut admin_override: bool) -> ReadInvestigationCancellation {
    let material: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("schema_version"), String::from("1.0.0")), (String::from("command"), String::from("cancel")), (String::from("request_id"), request_id.clone()), (String::from("owner_principal_id"), owner_principal_id.clone()), (String::from("task_id"), task_id.clone()), (String::from("idempotency_key"), idempotency_key.clone()), (String::from("requested_at"), String::new()), (String::from("admin_override"), String::new()), (String::from("execution_authority"), String::new())]);
    Default::default()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
#[allow(clippy::too_many_arguments)]
pub fn build_read_investigation_completion(mut task_id: String, mut attempt_id: String, mut attempt_number: i64, mut owner_principal_id: String, mut request_idempotency_key: String, mut correlation_id: String, mut origin: ReadInvestigationOrigin, mut status: String, mut terminal_reason: String, mut summary: Option<String>, mut evidence_refs: Vec<String>, mut usage: ReadInvestigationCompletionUsage, mut started_at: String, mut finished_at: String, mut completed_at: String, mut retention_until: String) -> ReadInvestigationCompletion {
    let material: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("schema_version"), String::from("1.0.0")), (String::from("completion_id"), read_investigation_completion_id(task_id.clone(), attempt_id.clone(), attempt_number)), (String::from("task_id"), task_id.clone()), (String::from("attempt_id"), attempt_id.clone()), (String::from("attempt_number"), String::new()), (String::from("owner_principal_id"), owner_principal_id.clone()), (String::from("request_idempotency_key"), request_idempotency_key.clone()), (String::from("correlation_id"), correlation_id.clone()), (String::from("origin"), String::new()), (String::from("status"), status.clone()), (String::from("terminal_reason"), terminal_reason.clone()), (String::from("summary"), (summary.clone()).unwrap_or_default()), (String::from("evidence_refs"), String::new()), (String::from("usage"), String::new()), (String::from("started_at"), String::new()), (String::from("finished_at"), String::new()), (String::from("completed_at"), String::new()), (String::from("retention_until"), String::new()), (String::from("trusted"), String::new()), (String::from("execution_authority"), String::new())]);
    Default::default()
}

pub const PUBLIC_EXPORTS: &[&str] = &["READ_INVESTIGATION_COMPLETION_CONSUMER_GROUP", "READ_INVESTIGATION_COMPLETION_TOPIC", "READ_INVESTIGATION_CONSUMER_GROUP", "READ_INVESTIGATION_REQUEST_TOPIC", "ReadInvestigationCompletion", "ReadInvestigationCompletionUsage", "ReadInvestigationOrigin", "ReadInvestigationIntent", "ReadInvestigationCancellation", "ReadInvestigationProposalBody", "ReadInvestigationRequest", "ReadInvestigationSelector", "ReadInvestigationTaskBudget", "build_read_investigation_request", "build_read_investigation_cancellation", "build_read_investigation_completion", "read_investigation_completion_digest", "read_investigation_completion_id", "read_investigation_request_digest", "read_investigation_task_id"];
