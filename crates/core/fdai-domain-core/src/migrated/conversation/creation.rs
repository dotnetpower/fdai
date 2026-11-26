#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct CreationForbiddenError {
    pub message: String,
}

impl CreationForbiddenError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for CreationForbiddenError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for CreationForbiddenError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct CreateIncidentCommand {
    pub initialized: bool,
}

impl CreateIncidentCommand {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn create(&self, mut principal: String, mut correlation_keys: Vec<String>, mut severity: String, mut member_event_ids: Vec<String>, mut confirmed: bool) -> Result<String, &'static str> {
        let _ = require_floor(principal.clone(), String::from("create_incident")).unwrap_or_else(|_| ());
        if !(confirmed) {
            return Err("explicit incident creation confirmation is required");
        }
        Ok(String::new())
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct CreateScheduledTaskCommand {
    pub initialized: bool,
}

impl CreateScheduledTaskCommand {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    #[allow(clippy::too_many_arguments)]
    pub async fn create(&self, mut principal: String, mut name: String, mut interval_seconds: f64, mut event_type: String, mut resource_ref: Option<String>, mut event_payload: Option<std::collections::BTreeMap<String, String>>, mut task_id: Option<String>, mut cron_expression: Option<String>, mut timezone: String, mut isolation_profile: Option<String>, mut continuation_mode: String, mut continuation_origin: Option<String>) -> Result<String, &'static str> {
        let _ = require_floor(principal.clone(), String::from("create_scheduled_task")).unwrap_or_else(|_| ());
        if (task_id.is_some()) && (!((task_id.clone()).is_some())) {
            return Err("ScheduledTask.task_id MUST be non-empty");
        }
        if let Some(mut task_id) = task_id.clone() {
            return Err("task_id task_idr already exists with different content");
        }
        Ok(String::new())
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn require_floor(mut principal: String, mut action: String) -> Result<(), &'static str> {
    if principal.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn same_schedule_definition(mut existing: String, mut requested: String) -> bool {
    if existing.is_empty() {
        return false;
    }
    false
}

pub const PUBLIC_EXPORTS: &[&str] = &["CreateIncidentCommand", "CreateScheduledTaskCommand", "CreationForbiddenError"];
