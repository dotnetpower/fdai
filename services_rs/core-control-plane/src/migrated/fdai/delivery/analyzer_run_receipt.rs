pub const ANALYZER_RUN_ID_ENV: &str = "FDAI_ANALYZER_RUN_ID";
pub const CONTAINER_APP_JOB_EXECUTION_NAME_ENV: &str = "CONTAINER_APP_JOB_EXECUTION_NAME";
pub const STATE_STORE_DSN_ENV: &str = "FDAI_STATE_STORE_DSN";
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct AnalyzerRunReceiptPersistenceError {
    pub message: String,
}

impl AnalyzerRunReceiptPersistenceError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for AnalyzerRunReceiptPersistenceError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for AnalyzerRunReceiptPersistenceError {}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn resolve_analyzer_run_id(mut environment: std::collections::BTreeMap<String, String>) -> Result<Option<String>, &'static str> {
    let run_id: String = { let _a = ((environment.clone()).get(ANALYZER_RUN_ID_ENV).cloned().unwrap_or_else(|| String::from(""))).trim().to_string(); if !_a.is_empty() { _a } else { ((environment.clone()).get(CONTAINER_APP_JOB_EXECUTION_NAME_ENV).cloned().unwrap_or_else(|| String::from(""))).trim().to_string() } };
    if (run_id.clone()).is_empty() {
        return Ok(None);
    }
    Ok(Some(run_id.clone()))
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn build_analyzer_run_receipt_store(mut environment: std::collections::BTreeMap<String, String>) -> Option<String> {
    let dsn: String = ((environment.clone()).get(STATE_STORE_DSN_ENV).cloned().unwrap_or_else(|| String::from(""))).trim().to_string();
    if (dsn.clone()).is_empty() {
        return None;
    }
    None
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub async fn record_analyzer_run_receipt(mut environment: std::collections::BTreeMap<String, String>, mut tick_id: String, mut recorded_at: String, mut report: std::collections::BTreeMap<String, String>) -> Result<(), &'static str> {
    let run_id: Option<String> = resolve_analyzer_run_id(environment.clone()).unwrap_or_else(|_| None);
    if run_id.is_none() {
        return Ok(());
    }
    let store: Option<String> = build_analyzer_run_receipt_store(environment.clone());
    let Some(mut store) = store.clone() else { return Ok(()); };
    Ok(())
}

pub const PUBLIC_EXPORTS: &[&str] = &["ANALYZER_RUN_ID_ENV", "AnalyzerRunReceiptPersistenceError", "CONTAINER_APP_JOB_EXECUTION_NAME_ENV", "build_analyzer_run_receipt_store", "record_analyzer_run_receipt", "resolve_analyzer_run_id"];
