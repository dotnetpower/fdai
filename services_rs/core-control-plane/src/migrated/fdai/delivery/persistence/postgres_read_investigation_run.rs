#[derive(Clone, Debug, Default, PartialEq)]
pub struct PostgresReadInvestigationRunStoreConfig {
    pub dsn: String,
    pub statement_timeout_ms: i64,
    pub connect_timeout_s: i64,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct PostgresReadInvestigationRunStore {
    pub initialized: bool,
}

impl PostgresReadInvestigationRunStore {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn verify_schema(&self) {
        if !self.initialized {
            return;
        }
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    #[allow(clippy::too_many_arguments)]
    pub async fn claim(&self, mut owner_principal_id: String, mut request: String, mut mode: String, mut lease_owner: String, mut lease_token: String, mut now: String, mut lease_seconds: i64, mut retention_seconds: i64) -> Result<(String, bool), &'static str> {
        let _ = aware(String::from("claim now"), now.clone()).unwrap_or_else(|_| ());
        if (lease_seconds) < (1_i64) {
            return Err("lease_seconds MUST be  1");
        }
        if (retention_seconds) < (1_i64) {
            return Err("retention_seconds MUST be  1");
        }
        Ok((String::new(), false))
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::too_many_arguments)]
    pub async fn reclaim(&self, mut owner_principal_id: String, mut idempotency_key: String, mut request_digest: String, mut mode: String, mut expected_revision: i64, mut lease_owner: String, mut lease_token: String, mut now: String, mut lease_seconds: i64, mut retention_seconds: i64) -> Result<String, &'static str> {
        let _ = aware(String::from("reclaim now"), now.clone()).unwrap_or_else(|_| ());
        if (lease_seconds) < (1_i64) {
            return Err("lease_seconds MUST be  1");
        }
        if (retention_seconds) < (1_i64) {
            return Err("retention_seconds MUST be  1");
        }
        let row: std::collections::BTreeMap<String, String> = self.leased_update(String::from("UPDATE read_investigation_run SET state = %s, mode = %s, revision = revision + 1, \" \"attempt_count = attempt_count + 1, updated_at = %s, \" \"retention_until = GREATEST(retention_until, %s), \" \"terminal_at = NULL, lease_owner = %s, lease_token = %s, lease_expires_at = %s, \" \"result = NULL, usage = NULL, failure_reason = NULL \" \"WHERE owner_principal_id = %s AND idempotency_key = %s AND request_digest = %s \" \"AND revision = %s AND state = ANY(%s) AND attempt_count < %s RETURNING \" f\"{_COLUMNS}"), Vec::new(), owner_principal_id.clone(), idempotency_key.clone()).await.unwrap_or_else(|_| std::collections::BTreeMap::new());
        Ok(String::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn get(&self, mut owner_principal_id: String, mut idempotency_key: String) -> Option<String> {
        if !self.initialized {
            return None;
        }
        None
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn get_by_task_id(&self, mut task_id: String) -> Option<String> {
        if !self.initialized {
            return None;
        }
        None
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn start(&self, mut owner_principal_id: String, mut idempotency_key: String, mut expected_revision: i64, mut lease_token: String, mut now: String) -> String {
        let _ = aware(String::from("start now"), now.clone()).unwrap_or_else(|_| ());
        let row: std::collections::BTreeMap<String, String> = self.leased_update(String::from("UPDATE read_investigation_run SET state = %s, revision = revision + 1, \" \"updated_at = %s WHERE owner_principal_id = %s AND idempotency_key = %s \" \"AND revision = %s AND lease_token = %s AND lease_expires_at > %s \" \"AND state = %s RETURNING \" f\"{_COLUMNS}"), Vec::new(), owner_principal_id.clone(), idempotency_key.clone()).await.unwrap_or_else(|_| std::collections::BTreeMap::new());
        String::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::too_many_arguments)]
    pub async fn renew(&self, mut owner_principal_id: String, mut idempotency_key: String, mut expected_revision: i64, mut lease_token: String, mut now: String, mut lease_seconds: i64, mut lease_ceiling_at: String) -> Result<String, &'static str> {
        let _ = aware(String::from("renew now"), now.clone()).unwrap_or_else(|_| ());
        let _ = aware(String::from("renew lease_ceiling_at"), lease_ceiling_at.clone()).unwrap_or_else(|_| ());
        if (lease_seconds) < (1_i64) {
            return Err("lease_seconds MUST be  1");
        }
        if (lease_ceiling_at.clone()) < (now.clone()) {
            return Err("lease_ceiling_at MUST be  now");
        }
        let row: std::collections::BTreeMap<String, String> = self.leased_update(String::from("UPDATE read_investigation_run SET revision = revision + 1, updated_at = %s, \" \"lease_expires_at = LEAST(%s, %s) \" \"WHERE owner_principal_id = %s AND idempotency_key = %s AND revision = %s \" \"AND lease_token = %s AND lease_expires_at > %s AND state = %s \" \"AND LEAST(%s, %s) > %s RETURNING \" f\"{_COLUMNS}"), Vec::new(), owner_principal_id.clone(), idempotency_key.clone()).await.unwrap_or_else(|_| std::collections::BTreeMap::new());
        Ok(String::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn request_cancel(&self, mut task_id: String, mut actor: String, mut is_admin: bool, mut now: String) -> Result<String, &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn finish_cancel(&self, mut owner_principal_id: String, mut idempotency_key: String, mut expected_revision: i64, mut lease_token: String, mut usage: String, mut now: String) -> String {
        let _ = aware(String::from("finish cancel now"), now.clone()).unwrap_or_else(|_| ());
        self.terminal_update(String::from("UPDATE read_investigation_run SET state = %s, revision = revision + 1, \" \"updated_at = %s, terminal_at = %s, lease_owner = NULL, lease_token = NULL, \" \"lease_expires_at = NULL, result = NULL, usage = %s::jsonb, failure_reason = %s \" \"WHERE owner_principal_id = %s AND idempotency_key = %s AND revision = %s \" \"AND lease_token = %s AND lease_expires_at > %s AND state = %s RETURNING \" f\"{_COLUMNS}"), Vec::new(), owner_principal_id.clone(), idempotency_key.clone()).await.unwrap_or_else(|_| String::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::too_many_arguments)]
    pub async fn complete(&self, mut owner_principal_id: String, mut idempotency_key: String, mut expected_revision: i64, mut lease_token: String, mut result: String, mut usage: String, mut now: String) -> String {
        let _ = aware(String::from("complete now"), now.clone()).unwrap_or_else(|_| ());
        self.terminal_update(String::from("UPDATE read_investigation_run SET state = %s, revision = revision + 1, \" \"updated_at = %s, terminal_at = %s, lease_owner = NULL, lease_token = NULL, \" \"lease_expires_at = NULL, result = %s::jsonb, usage = %s::jsonb, \" \"failure_reason = NULL WHERE owner_principal_id = %s AND idempotency_key = %s \" \"AND revision = %s AND lease_token = %s AND lease_expires_at > %s \" \"AND state = ANY(%s) AND request_digest = %s RETURNING \" f\"{_COLUMNS}"), Vec::new(), owner_principal_id.clone(), idempotency_key.clone()).await.unwrap_or_else(|_| String::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::too_many_arguments)]
    pub async fn fail(&self, mut owner_principal_id: String, mut idempotency_key: String, mut expected_revision: i64, mut lease_token: String, mut failure_reason: String, mut usage: String, mut now: String, mut state: String) -> Result<String, &'static str> {
        let _ = aware(String::from("fail now"), now.clone()).unwrap_or_else(|_| ());
        Ok(self.terminal_update(String::from("UPDATE read_investigation_run SET state = %s, revision = revision + 1, \" \"updated_at = %s, terminal_at = %s, lease_owner = NULL, lease_token = NULL, \" \"lease_expires_at = NULL, result = NULL, usage = %s::jsonb, failure_reason = %s \" \"WHERE owner_principal_id = %s AND idempotency_key = %s AND revision = %s \" \"AND lease_token = %s AND lease_expires_at > %s AND state = ANY(%s) RETURNING \" f\"{_COLUMNS}"), Vec::new(), owner_principal_id.clone(), idempotency_key.clone()).await.unwrap_or_else(|_| String::new()))
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn reconcile_expired(&self, mut now: String, mut limit: i64) -> Vec<String> {
        if !self.initialized {
            return Vec::new();
        }
        Vec::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn purge_retained(&self, mut now: String, mut limit: i64) -> Vec<(String, String)> {
        if !self.initialized {
            return Vec::new();
        }
        Vec::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn leased_update(&self, mut query: String, mut params: Vec<String>, mut owner_principal_id: String, mut idempotency_key: String) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
        if self.run_exists(owner_principal_id.clone(), idempotency_key.clone()).await {
            return Err("read investigation lease or revision conflict");
        }
        Err("read investigation run was not found")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn terminal_update(&self, mut query: String, mut params: Vec<String>, mut owner_principal_id: String, mut idempotency_key: String) -> Result<String, &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn insert_completion(&self, mut connection: String, mut record: String) -> Result<(), &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn run_exists(&self, mut owner_principal_id: String, mut idempotency_key: String) -> bool {
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
pub fn limit(mut value: i64, mut maximum: i64) -> Result<(), &'static str> {
    if !(((1_i64) <= (value)) && ((value) <= (maximum))) {
        return Err("limit MUST be in 1 maximum");
    }
    Ok(())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn aware(mut name: String, mut value: String) -> Result<(), &'static str> {
    if name.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

pub const PUBLIC_EXPORTS: &[&str] = &["PostgresReadInvestigationRunStore", "PostgresReadInvestigationRunStoreConfig"];
