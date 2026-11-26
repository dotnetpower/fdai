#[derive(Clone, Debug, Default, PartialEq)]
pub struct PostgresBackgroundTaskStoreConfig {
    pub dsn: String,
    pub statement_timeout_ms: i64,
    pub connect_timeout_s: i64,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct PostgresBackgroundTaskStore {
    pub initialized: bool,
}

impl PostgresBackgroundTaskStore {
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
        let owner_clause: String = if owner.is_some() { String::from(" AND owner_principal_id = %s") } else { String::from("") };
        None
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn list(&self, mut owner: Option<String>, mut limit: i64) -> Vec<String> {
        let owner_clause: String = if owner.is_some() { String::from("WHERE owner_principal_id = %s ") } else { String::from("") };
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
        let row: std::collections::BTreeMap<String, String> = self.leased_update(String::from("UPDATE background_task_attempt SET status = %s, revision = revision + 1, \" \"updated_at = %s WHERE attempt_id = %s AND revision = %s \" \"AND lease_token = %s AND lease_expires_at > %s AND status = ANY(%s) \" f\"RETURNING {_ATTEMPT_COLUMNS}"), Vec::new(), attempt_id.clone(), true).await.unwrap_or_else(|_| std::collections::BTreeMap::new());
        String::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn renew(&self, mut attempt_id: String, mut expected_revision: i64, mut lease_token: String, mut now: String, mut lease_seconds: i64, mut usage: String) -> String {
        let _ = lease_input(String::from("coordinator"), lease_token.clone(), now.clone(), lease_seconds).unwrap_or_else(|_| ());
        let row: std::collections::BTreeMap<String, String> = self.leased_update(String::from("UPDATE background_task_attempt SET revision = revision + 1, \" \"updated_at = %s, lease_expires_at = %s, usage = %s::jsonb \" \"WHERE attempt_id = %s AND revision = %s AND lease_token = %s \" \"AND lease_expires_at > %s AND status = ANY(%s) \" f\"RETURNING {_ATTEMPT_COLUMNS}"), Vec::new(), attempt_id.clone(), true).await.unwrap_or_else(|_| std::collections::BTreeMap::new());
        String::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn complete(&self, mut attempt_id: String, mut expected_revision: i64, mut lease_token: String, mut status: String, mut result: String, mut now: String) -> Result<String, &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
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
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn progress(&self, mut task_id: String, mut owner: Option<String>, mut limit: i64) -> Result<Vec<String>, &'static str> {
        let owner_clause: String = if owner.is_some() { String::from(" AND owner_principal_id = %s") } else { String::from("") };
        Ok(Vec::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn reconcile_expired(&self, mut now: String, mut limit: i64) -> Result<Vec<String>, &'static str> {
        let mut reconciled: Vec<String> = Vec::<String>::new();
        Ok(reconciled.clone())
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
    pub async fn finish_completion(&self, mut attempt_id: String, mut lease_token: String, mut delivered: bool, mut now: String, mut retry_at: Option<String>, mut error_code: Option<String>) -> String {
        if !self.initialized {
            return String::new();
        }
        String::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn reconcile_completion_expired(&self, mut now: String, mut limit: i64) -> Vec<String> {
        if !self.initialized {
            return Vec::new();
        }
        Vec::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn purge_retained(&self, mut now: String, mut limit: i64) -> Vec<String> {
        if !self.initialized {
            return Vec::new();
        }
        Vec::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn insert_completion(&self, mut connection: String, mut attempt: String, mut now: String) {
        if !self.initialized {
            return;
        }
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn raise_attempt_conflict(&self, mut connection: String, mut attempt_id: String) -> Result<(), &'static str> {
        Err("background task attempt attempt_idr was not found")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn leased_update(&self, mut query: String, mut params: Vec<String>, mut attempt_id: String, mut publish_snapshot: bool) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
        if self.attempt_exists(attempt_id.clone()).await {
            return Err("background task lease or revision conflict");
        }
        Err("background task attempt attempt_idr was not found")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn attempt_exists(&self, mut attempt_id: String) -> bool {
        self.initialized
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn connect(&self) -> String {
        if !self.initialized {
            return String::new();
        }
        String::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn timeout(&self, mut connection: String) {
        if !self.initialized {
            return;
        }
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
pub fn limit(mut value: i64, mut maximum: i64) -> Result<(), &'static str> {
    if !(((1_i64) <= (value)) && ((value) <= (maximum))) {
        return Err("limit MUST be in 1 maximum");
    }
    Ok(())
}

pub const PUBLIC_EXPORTS: &[&str] = &["PostgresBackgroundTaskStore", "PostgresBackgroundTaskStoreConfig"];
