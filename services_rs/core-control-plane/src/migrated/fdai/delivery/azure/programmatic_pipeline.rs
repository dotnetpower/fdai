#[derive(Clone, Debug, Default, PartialEq)]
pub struct AzureIsolatedPipelineRunnerConfig {
    pub max_submission_bytes: i64,
}

pub trait AzurePipelineSubmissionClient {
    fn submit(&self, spec: String, broker: String) -> String;
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct AzureIsolatedPipelineRunner {
    pub initialized: bool,
}

impl AzureIsolatedPipelineRunner {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn run(&self, mut spec: String, mut broker: String) -> Result<String, &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn cancel(&self, mut run_id: String) -> Result<bool, &'static str> {
        if (!(true)) || ((run_id.trim().to_string()).is_empty()) {
            return Err("Azure pipeline run_id MUST be non-empty");
        }
        Ok(false)
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["AzureIsolatedPipelineRunner", "AzureIsolatedPipelineRunnerConfig", "AzurePipelineSubmissionClient"];
