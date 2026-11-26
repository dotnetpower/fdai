pub const DEFAULT_ANALYZER_RECEIPT_RETENTION: i64 = 500;

#[derive(Clone, Debug, Default, PartialEq)]
pub struct StateStoreAnalyzerReceiptStore {
    pub state_store: String,
    pub retain_newest: Option<i64>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct StateStoreAnalyzerRunReceiptStore {
    pub state_store: String,
    pub retain_newest: i64,
}

pub const ANALYZER_RECEIPT_STATE_PREFIX: &str = "runtime:analyzer-finding-receipt:";
pub const ANALYZER_RUN_RECEIPT_STATE_PREFIX: &str = "runtime:analyzer-tick-receipt:";
pub const ANALYZER_RUN_RECEIPT_SCHEMA_VERSION: &str = "1.3.0";
pub const PER_TICK_OBSERVATION_FIELDS: &[&str] = &["detection_latency_seconds", "recorded_at"];
impl StateStoreAnalyzerReceiptStore {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn aclose(&self) {
        core::sync::atomic::compiler_fence(core::sync::atomic::Ordering::SeqCst);
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn record(&self, mut receipt: String) -> Result<(), &'static str> {
        Err("runtime_binding_required")
    }
}

impl StateStoreAnalyzerRunReceiptStore {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn aclose(&self) {
        core::sync::atomic::compiler_fence(core::sync::atomic::Ordering::SeqCst);
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn record(&self, mut run_id: String, mut tick_id: String, mut recorded_at: String, mut report: std::collections::BTreeMap<String, String>) -> Result<(), &'static str> {
        if ((run_id.trim().to_string()).is_empty()) || ((((run_id.clone()).len() as i64)) > (256_i64)) {
            return Err("analyzer run receipt id MUST be bounded text");
        }
        let value: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("schema_version"), String::from(ANALYZER_RUN_RECEIPT_SCHEMA_VERSION)), (String::from("run_id"), run_id.clone()), (String::from("tick_id"), tick_id.clone()), (String::from("attempt_id"), String::new()), (String::from("recorded_at"), String::new()), (String::from("report_digest"), String::new()), (String::from("report"), String::new()), (String::from("execution_authority"), String::new())]);
        Ok(())
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn immutable_content(mut value: std::collections::BTreeMap<String, String>) -> std::collections::BTreeMap<String, String> {
    std::collections::BTreeMap::new()
}

pub const PUBLIC_EXPORTS: &[&str] = &["ANALYZER_RUN_RECEIPT_SCHEMA_VERSION", "ANALYZER_RECEIPT_STATE_PREFIX", "ANALYZER_RUN_RECEIPT_STATE_PREFIX", "DEFAULT_ANALYZER_RECEIPT_RETENTION", "StateStoreAnalyzerReceiptStore", "StateStoreAnalyzerRunReceiptStore"];
