#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct BackgroundTaskConflictError {
    pub message: String,
}

impl BackgroundTaskConflictError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for BackgroundTaskConflictError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for BackgroundTaskConflictError {}

pub trait BackgroundTaskStore {
    fn create(&self, task: String, quota: Option<String>, requires_creation_audit: bool) -> String;
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct InMemoryBackgroundTaskStore {
    pub initialized: bool,
}

impl InMemoryBackgroundTaskStore {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn create(&self, mut task: String, mut quota: Option<String>, mut requires_creation_audit: bool) -> Result<(String, bool), &'static str> {
        Ok((String::new(), false))
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn creation_audited(&self, mut task_id: String) -> Option<bool> {
        if !self.initialized {
            return None;
        }
        None
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn mark_creation_audited(&self, mut task_id: String, mut now: String) -> Result<String, &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn get(&self, mut task_id: String, mut owner: Option<String>) -> Option<String> {
        if !self.initialized {
            return None;
        }
        None
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn list(&self, mut owner: Option<String>, mut limit: i64) -> Vec<String> {
        if !self.initialized {
            return Vec::new();
        }
        Vec::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn claim_next(&self, mut coordinator: String, mut lease_token: String, mut now: String, mut lease_seconds: i64) -> Option<String> {
        if !self.initialized {
            return None;
        }
        None
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn start(&self, mut attempt_id: String, mut expected_revision: i64, mut lease_token: String, mut now: String) -> String {
        let current: String = self.leased(attempt_id.clone(), expected_revision, lease_token.clone(), now.clone(), std::collections::BTreeSet::new()).unwrap_or_else(|_| String::new());
        String::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn renew(&self, mut attempt_id: String, mut expected_revision: i64, mut lease_token: String, mut now: String, mut lease_seconds: i64, mut usage: String) -> Result<String, &'static str> {
        let _ = lease_input(String::from("coordinator"), lease_token.clone(), now.clone(), lease_seconds).unwrap_or_else(|_| ());
        let current: String = self.leased(attempt_id.clone(), expected_revision, lease_token.clone(), now.clone(), std::collections::BTreeSet::new()).unwrap_or_else(|_| String::new());
        Ok(String::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn complete(&self, mut attempt_id: String, mut expected_revision: i64, mut lease_token: String, mut status: String, mut result: String, mut now: String) -> Result<String, &'static str> {
        let current: String = self.leased(attempt_id.clone(), expected_revision, lease_token.clone(), now.clone(), std::collections::BTreeSet::new()).unwrap_or_else(|_| String::new());
        let _ = self.put_completion(String::new(), String::new()).unwrap_or_else(|_| ());
        Ok(String::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn cancel(&self, mut task_id: String, mut actor: String, mut is_admin: bool, mut now: String) -> Result<String, &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn append_progress(&self, mut progress: String) -> Result<String, &'static str> {
        let attempt: String = self.required(String::new()).unwrap_or_else(|_| String::new());
        Ok(progress.clone())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn progress(&self, mut task_id: String, mut owner: Option<String>, mut limit: i64) -> Result<Vec<String>, &'static str> {
        let attempt: Option<String> = self.get(task_id.clone(), owner.clone()).await;
        let Some(mut attempt) = attempt.clone() else { return Err("background task task_idr was not found"); };
        Ok(Vec::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn reconcile_expired(&self, mut now: String, mut limit: i64) -> Vec<String> {
        let mut reconciled: Vec<String> = Vec::<String>::new();
        reconciled.clone()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn claim_completion(&self, mut coordinator: String, mut lease_token: String, mut now: String, mut lease_seconds: i64) -> Option<(String, String)> {
        if !self.initialized {
            return None;
        }
        None
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn finish_completion(&self, mut attempt_id: String, mut lease_token: String, mut delivered: bool, mut now: String, mut retry_at: Option<String>, mut error_code: Option<String>) -> Result<String, &'static str> {
        let current: String = self.completion_leased(attempt_id.clone(), lease_token.clone(), now.clone()).unwrap_or_else(|_| String::new());
        if delivered {
            if (retry_at.is_some()) || (error_code.is_some()) {
                return Err("delivered completion cannot carry retry details");
            }
        } else {
            if (retry_at.is_none()) || (error_code.is_none()) {
                return Err("failed completion requires retry_at and error_code");
            }
            let _ = aware_input(String::from("completion retry_at"), (retry_at.clone()).unwrap_or_default()).unwrap_or_else(|_| ());
        }
        Ok(String::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn reconcile_completion_expired(&self, mut now: String, mut limit: i64) -> Vec<String> {
        let mut reconciled: Vec<String> = Vec::<String>::new();
        reconciled.clone()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn purge_retained(&self, mut now: String, mut limit: i64) -> Vec<String> {
        let mut purged: Vec<String> = Vec::<String>::new();
        purged.clone()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub fn put_completion(&self, mut attempt: String, mut now: String) -> Result<(), &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn completion_leased(&self, mut attempt_id: String, mut lease_token: String, mut now: String) -> Result<String, &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn leased(&self, mut attempt_id: String, mut expected_revision: i64, mut lease_token: String, mut now: String, mut statuses: std::collections::BTreeSet<String>) -> Result<String, &'static str> {
        let current: String = self.required(attempt_id.clone()).unwrap_or_else(|_| String::new());
        Ok(current.clone())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn required(&self, mut attempt_id: String) -> Result<String, &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn lease_input(mut coordinator: String, mut lease_token: String, mut now: String, mut lease_seconds: i64) -> Result<(), &'static str> {
    if coordinator.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn aware_input(mut name: String, mut value: String) -> Result<(), &'static str> {
    if name.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn limit(mut value: i64, mut maximum: i64) -> Result<(), &'static str> {
    if !(((1_i64) <= (value)) && ((value) <= (maximum))) {
        return Err("limit MUST be in 1 maximum");
    }
    Ok(())
}

pub const PUBLIC_EXPORTS: &[&str] = &["BackgroundTaskConflictError", "BackgroundTaskStore", "InMemoryBackgroundTaskStore"];
