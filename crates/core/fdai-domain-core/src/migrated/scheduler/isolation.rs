#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ScheduledRunIsolationError {
    pub message: String,
}

impl ScheduledRunIsolationError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for ScheduledRunIsolationError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for ScheduledRunIsolationError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ScheduledRunIsolationGuard {
    pub initialized: bool,
}

impl ScheduledRunIsolationGuard {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub fn authorize(&self, mut context_chars: i64, mut elapsed_seconds: f64, mut tool_id: Option<String>, mut prior_tool_calls: i64) -> Result<(), &'static str> {
        let Some(mut tool_id) = tool_id.clone() else { return Ok(()); };
        Ok(())
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn isolation_payload(mut profile: String) -> std::collections::BTreeMap<String, String> {
    std::collections::BTreeMap::from([(String::from("profile_id"), String::new()), (String::from("max_session_seconds"), String::new()), (String::from("max_context_chars"), String::new()), (String::from("max_tool_calls"), String::new()), (String::from("allowed_tool_ids"), String::new()), (String::from("command_sandbox_profile_id"), String::new())])
}

pub const PUBLIC_EXPORTS: &[&str] = &["ScheduledRunIsolationError", "ScheduledRunIsolationGuard", "isolation_payload"];
