pub const MAX_BIGINT: i64 = 9223372036854775807;

#[derive(Clone, Debug, Default, PartialEq)]
pub struct BackgroundTaskProjectionBudget {
    pub max_wall_seconds: i64,
    pub max_tokens: i64,
    pub max_cost_microusd: i64,
    pub max_tool_calls: i64,
    pub max_progress_events: i64,
}

impl BackgroundTaskProjectionBudget {
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
pub struct BackgroundTaskProjectionUsage {
    pub tokens: i64,
    pub cost_microusd: i64,
    pub tool_calls: i64,
}

impl BackgroundTaskProjectionUsage {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !(0_i64..=10000000_i64).contains(&self.tokens) { return Err("tokens out of bounds"); }
        if !(0_i64..=10000000_i64).contains(&self.cost_microusd) { return Err("cost_microusd out of bounds"); }
        if !(0_i64..=100_i64).contains(&self.tool_calls) { return Err("tool_calls out of bounds"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct BackgroundTaskProjectionEnvelope {
    pub schema_version: String,
    pub projection_id: String,
    pub record_kind: String,
    pub task_id: String,
    pub owner_principal_id: String,
    pub attempt_id: String,
    pub recorded_at: String,
    pub retention_until: String,
    pub usage: Box<BackgroundTaskProjectionUsage>,
    pub projection_digest: String,
    pub execution_authority: bool,
    pub task_kind: Option<String>,
    pub status: Option<String>,
    pub revision: Option<i64>,
    pub projection_sequence: Option<i64>,
    pub created_at: Option<String>,
    pub updated_at: Option<String>,
    pub lease_expires_at: Option<String>,
    #[allow(clippy::type_complexity)]
    pub budget: Option<Box<BackgroundTaskProjectionBudget>>,
    pub request_summary: Option<String>,
    pub request_truncated: Option<bool>,
    pub accountable_agent: Option<String>,
    pub result_summary: Option<String>,
    pub result_truncated: Option<bool>,
    pub evidence_refs: Vec<String>,
    pub evidence_truncated: Option<bool>,
    pub terminal_reason: Option<String>,
    pub started_at: Option<String>,
    pub finished_at: Option<String>,
    pub completion_state: Option<String>,
    pub completion_attempt_count: Option<i64>,
    pub progress_watermark: Option<i64>,
    pub progress_sequence: Option<i64>,
    pub progress_order: Option<i64>,
    pub progress_kind: Option<String>,
    pub progress_message: Option<String>,
    pub progress_at: Option<String>,
}

impl BackgroundTaskProjectionEnvelope {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.schema_version.as_str(), "1.0.0") { return Err("invalid schema_version literal"); }
        if !matches!(self.record_kind.as_str(), "snapshot" | "progress") { return Err("invalid record_kind literal"); }
        if self.execution_authority { return Err("execution_authority violated literal bool invariant"); }
        Ok(())
    }
}

pub const BACKGROUND_TASK_PROJECTION_TOPIC: &str = "core.background-task.projections";
pub const BACKGROUND_TASK_PROJECTION_CONSUMER_GROUP: &str = "operator-background-task-projection-v1";
pub const TASK_ID_PATTERN: &str = "^background-task-(snapshot|progress)-[a-f0-9]{32}$";
pub const TERMINAL_TASK_STATUSES: &[&str] = &["succeeded", "failed", "cancelled", "timed_out", "unknown"];
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct BackgroundTaskProjectionContract {
    pub initialized: bool,
}

impl BackgroundTaskProjectionContract {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn reject_control_characters(mut value: String) -> Result<String, &'static str> {
        Ok(value.clone())
    }
}

impl BackgroundTaskProjectionEnvelope {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub fn validate_evidence_refs(mut value: Vec<String>) -> Result<Vec<String>, &'static str> {
        if ((((value.clone()).into_iter().collect::<std::collections::BTreeSet<String>>()).len() as i64)) != (((value.clone()).len() as i64)) {
            return Err("background task evidence_refs MUST be unique");
        }
        Ok(value.clone())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn validate_record(&self) -> Result<BackgroundTaskProjectionEnvelope, &'static str> {
        let _ = require_aware(Some(self.recorded_at.clone()), String::from("recorded_at")).unwrap_or_else(|_| ());
        let _ = require_aware(Some(self.retention_until.clone()), String::from("retention_until")).unwrap_or_else(|_| ());
        if (self.record_kind.clone()) == (String::from("snapshot")) {
            let _ = self.validate_snapshot().unwrap_or_else(|_| ());
        } else {
            let _ = self.validate_progress().unwrap_or_else(|_| ());
        }
        if (self.projection_digest.clone()) != (background_task_projection_digest(self.clone())) {
            return Err("background task projection digest does not match its content");
        }
        let expected_id: String = background_task_projection_id(self.record_kind.clone(), self.task_id.clone(), self.attempt_id.clone(), if (self.record_kind.clone()) == (String::from("snapshot")) { self.projection_sequence.clone() } else { self.progress_sequence.clone() }).unwrap_or_else(|_| String::new());
        if (self.projection_id.clone()) != (expected_id.clone()) {
            return Err("background task projection id does not match its content");
        }
        Ok(self.clone())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub fn validate_snapshot(&self) -> Result<(), &'static str> {
        let created_at: Option<String> = self.created_at.clone();
        let updated_at: Option<String> = self.updated_at.clone();
        if (created_at.is_none()) || (updated_at.is_none()) {
            return Err("background task snapshot record is incomplete");
        }
        let _ = require_aware(created_at.clone(), String::from("created_at")).unwrap_or_else(|_| ());
        let _ = require_aware(updated_at.clone(), String::from("updated_at")).unwrap_or_else(|_| ());
        if self.completion_state.is_none() {
            if self.completion_attempt_count.is_some() {
                return Err("snapshot completion_attempt_count requires completion_state");
            }
        } else {
            if self.completion_attempt_count.is_none() {
                return Err("snapshot completion_state requires completion_attempt_count");
            }
        }
        Ok(())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub fn validate_progress(&self) -> Result<(), &'static str> {
        let progress_at: Option<String> = self.progress_at.clone();
        let Some(mut progress_at) = progress_at.clone() else { return Err("background task progress record is incomplete"); };
        let _ = require_aware(Some(progress_at.clone()), String::from("progress_at")).unwrap_or_else(|_| ());
        if !(((progress_at.clone()) <= (self.recorded_at.clone())) && ((self.recorded_at.clone()) <= (self.retention_until.clone()))) {
            return Err("background task progress timestamps MUST be ordered");
        }
        if self.budget.is_some() {
            return Err("background task progress cannot carry a budget");
        }
        Ok(())
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn background_task_completion_subsequence(mut completion_state: Option<String>, mut completion_attempt_count: Option<i64>) -> Result<i64, &'static str> {
    if completion_state.is_none() {
        if let Some(mut completion_attempt_count) = completion_attempt_count.clone() {
            return Err("completion_attempt_count requires completion_state");
        }
        return Ok(0_i64);
    }
    let Some(mut completion_attempt_count) = completion_attempt_count.clone() else { return Err("completion_state requires completion_attempt_count"); };
    Ok(0_i64)
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn background_task_snapshot_sequence(mut revision: i64, mut completion_state: Option<String>, mut completion_attempt_count: Option<i64>) -> Result<i64, &'static str> {
    if (revision) < (1_i64) {
        return Err("background task revision MUST be positive");
    }
    Ok(((revision).saturating_mul(100_i64)).saturating_add(background_task_completion_subsequence(completion_state.clone(), completion_attempt_count.clone()).unwrap_or_else(|_| 0_i64)))
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn background_task_projection_id(mut record_kind: String, mut task_id: String, mut attempt_id: String, mut sequence: Option<i64>) -> Result<String, &'static str> {
    let Some(mut sequence) = sequence.clone() else { return Err("background task projection sequence is required"); };
    Ok(String::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn background_task_projection_digest(mut record: BackgroundTaskProjectionEnvelope) -> String {
    core::hint::black_box(String::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
#[allow(clippy::too_many_arguments)]
pub fn build_background_task_snapshot(mut task_id: String, mut owner_principal_id: String, mut attempt_id: String, mut task_kind: String, mut status: String, mut revision: i64, mut created_at: String, mut updated_at: String, mut retention_until: String, mut usage: BackgroundTaskProjectionUsage, mut budget: BackgroundTaskProjectionBudget, mut recorded_at: String, mut lease_expires_at: Option<String>, mut request_summary: Option<String>, mut request_truncated: bool, mut accountable_agent: Option<String>, mut result_summary: Option<String>, mut result_truncated: bool, mut evidence_refs: Vec<String>, mut evidence_truncated: bool, mut terminal_reason: Option<String>, mut started_at: Option<String>, mut finished_at: Option<String>, mut completion_state: Option<String>, mut completion_attempt_count: Option<i64>, mut progress_watermark: Option<i64>) -> BackgroundTaskProjectionEnvelope {
    let projection_sequence: i64 = background_task_snapshot_sequence(revision, completion_state.clone(), completion_attempt_count.clone()).unwrap_or_else(|_| 0_i64);
    let material: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("schema_version"), String::from("1.0.0")), (String::from("record_kind"), String::from("snapshot")), (String::from("projection_id"), background_task_projection_id(String::from("snapshot"), task_id.clone(), attempt_id.clone(), Some(projection_sequence)).unwrap_or_else(|_| String::new())), (String::from("task_id"), task_id.clone()), (String::from("owner_principal_id"), owner_principal_id.clone()), (String::from("attempt_id"), attempt_id.clone()), (String::from("recorded_at"), String::new()), (String::from("retention_until"), String::new()), (String::from("usage"), String::new()), (String::from("task_kind"), task_kind.clone()), (String::from("status"), status.clone()), (String::from("revision"), String::new()), (String::from("projection_sequence"), String::new()), (String::from("created_at"), String::new()), (String::from("updated_at"), String::new()), (String::from("lease_expires_at"), String::new()), (String::from("budget"), String::new()), (String::from("request_summary"), (request_summary.clone()).unwrap_or_default()), (String::from("request_truncated"), String::new()), (String::from("accountable_agent"), (accountable_agent.clone()).unwrap_or_default()), (String::from("result_summary"), (result_summary.clone()).unwrap_or_default()), (String::from("result_truncated"), String::new()), (String::from("evidence_refs"), String::new()), (String::from("evidence_truncated"), String::new()), (String::from("terminal_reason"), (terminal_reason.clone()).unwrap_or_default()), (String::from("started_at"), String::new()), (String::from("finished_at"), String::new()), (String::from("completion_state"), (completion_state.clone()).unwrap_or_default()), (String::from("completion_attempt_count"), String::new()), (String::from("progress_watermark"), String::new()), (String::from("execution_authority"), String::new())]);
    Default::default()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
#[allow(clippy::too_many_arguments)]
pub fn build_background_task_progress(mut task_id: String, mut owner_principal_id: String, mut attempt_id: String, mut progress_sequence: i64, mut progress_order: i64, mut progress_kind: String, mut progress_message: String, mut progress_at: String, mut retention_until: String, mut usage: BackgroundTaskProjectionUsage, mut recorded_at: Option<String>) -> BackgroundTaskProjectionEnvelope {
    let effective_recorded_at: String = if recorded_at.is_none() { progress_at.clone() } else { (recorded_at.clone()).unwrap_or_default() };
    let material: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("schema_version"), String::from("1.0.0")), (String::from("record_kind"), String::from("progress")), (String::from("projection_id"), background_task_projection_id(String::from("progress"), task_id.clone(), attempt_id.clone(), Some(progress_sequence)).unwrap_or_else(|_| String::new())), (String::from("task_id"), task_id.clone()), (String::from("owner_principal_id"), owner_principal_id.clone()), (String::from("attempt_id"), attempt_id.clone()), (String::from("recorded_at"), String::new()), (String::from("retention_until"), String::new()), (String::from("usage"), String::new()), (String::from("progress_sequence"), String::new()), (String::from("progress_order"), String::new()), (String::from("progress_kind"), progress_kind.clone()), (String::from("progress_message"), progress_message.clone()), (String::from("progress_at"), String::new()), (String::from("evidence_refs"), String::new()), (String::from("execution_authority"), String::new())]);
    Default::default()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn json_datetime(mut value: Option<String>) -> Option<String> {
    let Some(mut value) = value.clone() else { return None; };
    None
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn digest_material(mut material: std::collections::BTreeMap<String, String>) -> String {
    if material.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn require_aware(mut value: Option<String>, mut field: String) -> Result<(), &'static str> {
    if value.is_none() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

pub const PUBLIC_EXPORTS: &[&str] = &["BACKGROUND_TASK_PROJECTION_CONSUMER_GROUP", "BACKGROUND_TASK_PROJECTION_TOPIC", "BackgroundTaskProjectionBudget", "BackgroundTaskProjectionContract", "BackgroundTaskProjectionEnvelope", "BackgroundTaskProjectionUsage", "background_task_completion_subsequence", "background_task_projection_digest", "background_task_projection_id", "background_task_snapshot_sequence", "build_background_task_progress", "build_background_task_snapshot"];
