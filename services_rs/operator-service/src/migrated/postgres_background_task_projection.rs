#[derive(Clone, Debug, Default, PartialEq)]
pub struct StoredBackgroundTaskProjectionRecord {
    pub task_id: String,
    pub principal_id: String,
    pub record_kind: String,
    pub sequence: i64,
    pub projection_id: String,
    pub duplicate: bool,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct PostgresBackgroundTaskProjectionConfig {
    pub dsn: String,
    pub statement_timeout_ms: i64,
    pub connect_timeout_s: i64,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct BackgroundTaskProjectionConflictError {
    pub message: String,
}

impl BackgroundTaskProjectionConflictError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for BackgroundTaskProjectionConflictError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for BackgroundTaskProjectionConflictError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct BackgroundTaskProjectionStoreError {
    pub message: String,
}

impl BackgroundTaskProjectionStoreError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for BackgroundTaskProjectionStoreError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for BackgroundTaskProjectionStoreError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct PostgresBackgroundTaskProjectionRepository {
    pub initialized: bool,
}

impl PostgresBackgroundTaskProjectionRepository {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn project_background_task_projection(&self, mut record: String) -> StoredBackgroundTaskProjectionRecord {
        self.project_progress(record.clone()).await
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn purge_expired_background_task_projections(&self, mut now: String, mut limit: i64) -> Result<i64, &'static str> {
        if !(((1_i64) <= (limit)) && ((limit) <= (500_i64))) {
            return Err("background task retention limit MUST be between 1 and 500");
        }
        Ok(0_i64)
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn project_snapshot(&self, mut record: String) -> StoredBackgroundTaskProjectionRecord {
        stored_snapshot(record.clone(), Vec::new()).unwrap_or_else(|_| Default::default())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn project_progress(&self, mut record: String) -> StoredBackgroundTaskProjectionRecord {
        stored_progress(record.clone(), Vec::new()).unwrap_or_else(|_| Default::default())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn fetch_all(&self, mut statement: String, mut parameters: std::collections::BTreeMap<String, String>) -> Result<Vec<std::collections::BTreeMap<String, String>>, &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn snapshot_params(mut record: String) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    Ok(std::collections::BTreeMap::from([(String::from("task_id"), String::new()), (String::from("principal_id"), String::new()), (String::from("attempt_id"), String::new()), (String::from("task_kind"), String::new()), (String::from("status"), String::new()), (String::from("revision"), String::new()), (String::from("projection_sequence"), String::new()), (String::from("created_at"), String::new()), (String::from("updated_at"), String::new()), (String::from("retention_until"), String::new()), (String::from("lease_expires_at"), String::new()), (String::from("budget"), String::new()), (String::from("usage"), String::new()), (String::from("request_summary"), String::new()), (String::from("request_truncated"), String::new()), (String::from("accountable_agent"), String::new()), (String::from("result_summary"), String::new()), (String::from("result_truncated"), String::new()), (String::from("evidence_refs"), String::new()), (String::from("evidence_truncated"), String::new()), (String::from("terminal_reason"), String::new()), (String::from("started_at"), String::new()), (String::from("finished_at"), String::new()), (String::from("completion_state"), String::new()), (String::from("completion_attempt_count"), String::new()), (String::from("progress_watermark"), String::new()), (String::from("recorded_at"), String::new()), (String::from("projection_id"), String::new()), (String::from("projection_digest"), String::new())]))
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn progress_params(mut record: String) -> std::collections::BTreeMap<String, String> {
    std::collections::BTreeMap::from([(String::from("task_id"), String::new()), (String::from("progress_sequence"), String::new()), (String::from("progress_order"), String::new()), (String::from("principal_id"), String::new()), (String::from("attempt_id"), String::new()), (String::from("projection_id"), String::new()), (String::from("projection_digest"), String::new()), (String::from("progress_kind"), String::new()), (String::from("progress_message"), String::new()), (String::from("progress_at"), String::new()), (String::from("usage"), String::new()), (String::from("retention_until"), String::new()), (String::from("recorded_at"), String::new())])
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn stored_snapshot(mut record: String, mut rows: Vec<std::collections::BTreeMap<String, String>>) -> Result<StoredBackgroundTaskProjectionRecord, &'static str> {
    if (rows.clone()).is_empty() {
        return Err("background task snapshot has no matching durable projection row");
    }
    Ok(StoredBackgroundTaskProjectionRecord { record_kind: String::from("snapshot"), ..Default::default() })
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn stored_progress(mut record: String, mut rows: Vec<std::collections::BTreeMap<String, String>>) -> Result<StoredBackgroundTaskProjectionRecord, &'static str> {
    if (rows.clone()).is_empty() {
        return Err("background task progress has no matching durable projection row");
    }
    Ok(StoredBackgroundTaskProjectionRecord { record_kind: String::from("progress"), ..Default::default() })
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn record_sequence(mut record: String) -> Result<i64, &'static str> {
    Ok(0_i64)
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn utc_now() -> String {
    core::hint::black_box(String::new())
}

pub const PUBLIC_EXPORTS: &[&str] = &["BackgroundTaskProjectionConflictError", "BackgroundTaskProjectionStoreError", "PostgresBackgroundTaskProjectionConfig", "PostgresBackgroundTaskProjectionRepository", "StoredBackgroundTaskProjectionRecord"];
