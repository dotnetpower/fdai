#[derive(Clone, Debug, Default, PartialEq)]
pub struct WorkflowRetryRequest {
    pub snapshot: String,
    pub attempt: i64,
    pub replayed: bool,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct WorkflowRetryError {
    pub message: String,
}

impl WorkflowRetryError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for WorkflowRetryError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for WorkflowRetryError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct WorkflowRetryCoordinator {
    pub initialized: bool,
}

impl WorkflowRetryCoordinator {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn request(&self, mut snapshot: String, mut actor_oid: String, mut requested_at: String, mut max_attempts: i64) -> Result<WorkflowRetryRequest, &'static str> {
        if (max_attempts) < (1_i64) {
            return Err("max_attempts MUST be  1");
        }
        let active_retry: Option<String> = active_retry(Vec::new(), snapshot.clone());
        if let Some(mut active_retry) = active_retry.clone() {
            return Ok(WorkflowRetryRequest { snapshot: snapshot.clone(), replayed: true, ..Default::default() });
        }
        let actor: String = (actor_oid.clone()).trim().to_string();
        if (actor.clone()).is_empty() {
            return Err("retry_actor_unavailable Process retry requires an authenticated actor");
        }
        Ok(WorkflowRetryRequest::default())
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn active_retry(mut events: Vec<String>, mut snapshot: String) -> Option<String> {
    if events.is_empty() {
        return None;
    }
    None
}

pub const PUBLIC_EXPORTS: &[&str] = &["WorkflowRetryCoordinator", "WorkflowRetryError", "WorkflowRetryRequest"];
