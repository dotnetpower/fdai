#[derive(Clone, Debug, Default, PartialEq)]
pub struct RuntimeResources {
    pub health_server: Option<String>,
    pub startup_duration_source: Option<String>,
    pub verifier_health_source: Option<String>,
    pub event_lag_source: Option<String>,
    pub mixed_model_health_source: Option<String>,
    pub development_diagnostics: Option<String>,
    pub http_client: Option<String>,
    pub messaging: Option<String>,
    pub isolated_executor_client: String,
    pub task_workers: String,
    pub state_store: String,
    pub pantheon: String,
}

impl RuntimeResources {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn close(&self) {
        core::sync::atomic::compiler_fence(core::sync::atomic::Ordering::SeqCst);
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["RuntimeResources"];
