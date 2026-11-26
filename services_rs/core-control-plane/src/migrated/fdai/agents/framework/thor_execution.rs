#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ExecutionResourceUnavailableError {
    pub message: String,
}

impl ExecutionResourceUnavailableError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for ExecutionResourceUnavailableError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for ExecutionResourceUnavailableError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct DispatchEntryRejectedError {
    pub message: String,
}

impl DispatchEntryRejectedError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for DispatchEntryRejectedError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for DispatchEntryRejectedError {}

pub trait ThorExecutionHost {
    fn must_shadow(&self) -> String;
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub async fn execute(mut host: String, mut run: String) -> Result<(), &'static str> {
    let mut release_run_lock: bool = false;
    if preflight_blocks_execution(host.clone(), run.clone()).await {
        release_run_lock = true;
        return Ok(());
    }
    let mut success: bool = invoke_executor(host.clone(), run.clone()).await.unwrap_or_else(|_| false);
    release_run_lock = false;
    Ok(())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub async fn preflight_blocks_execution(mut host: String, mut run: String) -> bool {
    if host.is_empty() {
        return false;
    }
    false
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub async fn invoke_executor(mut host: String, mut run: String) -> Result<bool, &'static str> {
    Ok(false)
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub async fn record_dispatch_start(mut host: String, mut run: String, mut resource_lock_ref: Option<String>) -> Result<(), &'static str> {
    if host.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub async fn claim_execution_resource(mut host: String, mut run: String) -> Result<bool, &'static str> {
    Ok(true)
}

pub const PUBLIC_EXPORTS: &[&str] = &["ExecutionResourceUnavailableError", "claim_execution_resource", "execute", "invoke_executor", "preflight_blocks_execution"];
