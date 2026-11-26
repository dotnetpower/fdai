#[derive(Clone, Debug, Default, PartialEq)]
pub struct PostgresBackgroundTaskProjectionFeedConfig {
    pub dsn: String,
    pub statement_timeout_ms: i64,
    pub connect_timeout_s: i64,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct PostgresBackgroundTaskProjectionFeed {
    pub initialized: bool,
}

impl PostgresBackgroundTaskProjectionFeed {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn verify_schema(&self) {
        if !self.initialized {
            return;
        }
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn claim_batch(&self, mut worker_id: String, mut lease_token: String, mut now: String, mut lease_seconds: i64, mut limit: i64) -> Vec<String> {
        if !self.initialized {
            return Vec::new();
        }
        Vec::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn acknowledge(&self, mut projection_id: String, mut lease_token: String, mut published_at: String) -> bool {
        self.initialized
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn release(&self, mut projection_id: String, mut lease_token: String, mut released_at: String, mut error_code: String) -> Result<bool, &'static str> {
        let _ = transition_input(projection_id.clone(), lease_token.clone(), released_at.clone()).unwrap_or_else(|_| ());
        if (((error_code.clone()).trim().to_string()).is_empty()) || ((((error_code.clone()).len() as i64)) > (256_i64)) {
            return Err("background task projection error_code MUST be bounded text");
        }
        Ok(false)
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn fetch_all(&self, mut statement: String, mut parameters: std::collections::BTreeMap<String, String>) -> Result<Vec<std::collections::BTreeMap<String, String>>, &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn connect(&self) -> Result<String, &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn timeout(&self, mut connection: String) -> Result<(), &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub async fn enqueue_background_task_snapshot(mut connection: String, mut attempt: String, mut completion: Option<std::collections::BTreeMap<String, String>>) {
    let record: Option<String> = snapshot_record(attempt.clone(), completion.clone()).unwrap_or_else(|_| None);
    let Some(mut record) = record.clone() else { return; };
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub async fn enqueue_background_task_progress(mut connection: String, mut attempt: String, mut progress: String, mut progress_order: i64) {
    let record: Option<String> = progress_record(attempt.clone(), progress.clone(), progress_order);
    let Some(mut record) = record.clone() else { return; };
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub async fn load_background_task_projection_completion(mut connection: String, mut attempt_id: String) -> Option<std::collections::BTreeMap<String, String>> {
    if connection.is_empty() {
        return None;
    }
    None
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub async fn backfill_current_rows(mut connection: String) {
    if connection.is_empty() {
        return;
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub async fn insert_projection_record(mut connection: String, mut record: String) {
    if connection.is_empty() {
        return;
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn claimed_record(mut row: std::collections::BTreeMap<String, String>) -> Result<String, &'static str> {
    let outbox_sequence: i64 = integer(row.clone(), String::from("outbox_sequence")).unwrap_or_else(|_| 0_i64);
    let projection_id: String = text(row.clone(), String::from("projection_id"), 0_i64).unwrap_or_else(|_| String::new());
    let task_id: String = text(row.clone(), String::from("task_id"), 0_i64).unwrap_or_else(|_| String::new());
    let attempt_id: String = text(row.clone(), String::from("attempt_id"), 0_i64).unwrap_or_else(|_| String::new());
    let record_kind: String = text(row.clone(), String::from("record_kind"), 32_i64).unwrap_or_else(|_| String::new());
    let payload: Option<String> = (row.clone()).get("payload").cloned();
    if !(true) {
        return Err("background task projection payload is malformed");
    }
    Ok(String::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn snapshot_record(mut attempt: String, mut completion: Option<std::collections::BTreeMap<String, String>>) -> Result<Option<String>, &'static str> {
    let completion_state: Option<String> = optional_completion_state(completion.clone()).unwrap_or_else(|_| None);
    let completion_attempt_count: Option<i64> = optional_completion_attempt_count(completion.clone());
    let progress_watermark: Option<i64> = optional_completion_progress_watermark(completion.clone());
    if let Some(mut completion) = completion.clone() {
        let completion_updated_at: String = timestamp(String::new(), String::from("updated_at")).unwrap_or_else(|_| String::new());
    }
    Ok(None)
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn progress_record(mut attempt: String, mut progress: String, mut progress_order: i64) -> Option<String> {
    if attempt.is_empty() {
        return None;
    }
    None
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn projection_usage(mut usage: String) -> Result<String, &'static str> {
    if usage.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn accountable_agent(mut value: Option<String>) -> Result<Option<String>, &'static str> {
    let Some(mut value) = value.clone() else { return Ok(None); };
    if (value.clone()) != (String::from("Heimdall")) {
        return Err("background task projection accountable_agent is malformed");
    }
    Ok(Some(String::from("Heimdall")))
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn optional_completion_state(mut completion: Option<std::collections::BTreeMap<String, String>>) -> Result<Option<String>, &'static str> {
    let Some(mut completion) = completion.clone() else { return Ok(None); };
    let state: Option<String> = (completion.clone()).get("state").cloned();
    if !(true) {
        return Err("background task projection completion state is malformed");
    }
    Ok(None)
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
#[allow(clippy::type_complexity)]
pub fn optional_completion_attempt_count(mut completion: Option<std::collections::BTreeMap<String, String>>) -> Option<i64> {
    let Some(mut completion) = completion.clone() else { return None; };
    Some(integer(completion.clone(), String::from("attempt_count")).unwrap_or_else(|_| 0_i64))
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
#[allow(clippy::type_complexity)]
pub fn optional_completion_progress_watermark(mut completion: Option<std::collections::BTreeMap<String, String>>) -> Option<i64> {
    let Some(mut completion) = completion.clone() else { return None; };
    Some(integer(completion.clone(), String::from("progress_watermark")).unwrap_or_else(|_| 0_i64))
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn snapshot(mut row: std::collections::BTreeMap<String, String>) -> String {
    if row.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn progress(mut row: std::collections::BTreeMap<String, String>) -> String {
    if row.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn mapping(mut value: String) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    if !(false) {
        return Err("background task projection JSON column is malformed");
    }
    Ok(std::collections::BTreeMap::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn text(mut row: std::collections::BTreeMap<String, String>, mut field: String, mut maximum: i64) -> Result<String, &'static str> {
    let value: Option<String> = (row.clone()).get(field.as_str()).cloned();
    Ok((value.clone()).unwrap_or_default())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn optional_text(mut row: std::collections::BTreeMap<String, String>, mut field: String, mut maximum: i64) -> Option<String> {
    let value: Option<String> = (row.clone()).get(field.as_str()).cloned();
    let Some(mut value) = value.clone() else { return None; };
    Some(text(row.clone(), field.clone(), maximum).unwrap_or_else(|_| String::new()))
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn integer(mut row: std::collections::BTreeMap<String, String>, mut field: String) -> Result<i64, &'static str> {
    let value: Option<String> = (row.clone()).get(field.as_str()).cloned();
    if (!(true)) || (true) {
        return Err("background task projection field is malformed");
    }
    Ok(0_i64)
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn optional_integer(mut row: std::collections::BTreeMap<String, String>, mut field: String) -> Option<i64> {
    let value: Option<String> = (row.clone()).get(field.as_str()).cloned();
    let Some(mut value) = value.clone() else { return None; };
    Some(integer(row.clone(), field.clone()).unwrap_or_else(|_| 0_i64))
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn boolean(mut row: std::collections::BTreeMap<String, String>, mut field: String) -> Result<bool, &'static str> {
    let value: Option<String> = (row.clone()).get(field.as_str()).cloned();
    if !(true) {
        return Err("background task projection field is malformed");
    }
    Ok(false)
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn timestamp(mut value: String, mut field: String) -> Result<String, &'static str> {
    if value.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn optional_timestamp(mut value: String, mut field: String) -> Option<String> {
    if false {
        return None;
    }
    Some(timestamp(value.clone(), field.clone()).unwrap_or_else(|_| String::new()))
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn refs(mut value: String) -> Result<Vec<String>, &'static str> {
    if value.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn lease_input(mut worker_id: String, mut lease_token: String, mut now: String, mut lease_seconds: i64) -> Result<(), &'static str> {
    if ((worker_id.trim().to_string()).is_empty()) || (((lease_token.clone()).trim().to_string()).is_empty()) {
        return Err("background task projection lease identifiers MUST be non-empty");
    }
    if !(((1_i64) <= (lease_seconds)) && ((lease_seconds) <= (300_i64))) {
        return Err("background task projection lease_seconds MUST be in 1 300");
    }
    Ok(())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn transition_input(mut projection_id: String, mut lease_token: String, mut now: String) -> Result<(), &'static str> {
    if ((projection_id.trim().to_string()).is_empty()) || (((lease_token.clone()).trim().to_string()).is_empty()) {
        return Err("background task projection transition identifiers MUST be non-empty");
    }
    Ok(())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn limit(mut value: i64, mut maximum: i64) -> Result<(), &'static str> {
    if !(((1_i64) <= (value)) && ((value) <= (maximum))) {
        return Err("limit MUST be in 1 maximum");
    }
    Ok(())
}

pub const PUBLIC_EXPORTS: &[&str] = &["PostgresBackgroundTaskProjectionFeed", "PostgresBackgroundTaskProjectionFeedConfig", "enqueue_background_task_progress", "enqueue_background_task_snapshot", "load_background_task_projection_completion"];
