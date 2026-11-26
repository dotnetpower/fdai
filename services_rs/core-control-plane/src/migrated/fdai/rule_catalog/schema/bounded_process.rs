#[derive(Clone, Debug, Default, PartialEq)]
pub struct BoundedProcessResult {
    pub returncode: i64,
    pub stdout: Vec<u8>,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ProcessOutputLimitError {
    pub message: String,
}

impl ProcessOutputLimitError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for ProcessOutputLimitError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for ProcessOutputLimitError {}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn run_bounded_process(mut command: Vec<String>, mut input_data: Option<Vec<u8>>, mut timeout_seconds: f64, mut max_stdout_bytes: i64) -> Result<BoundedProcessResult, &'static str> {
    if (command.clone()).is_empty() {
        return Err("command MUST be non-empty");
    }
    if (max_stdout_bytes) <= (0_i64) {
        return Err("max_stdout_bytes MUST be positive");
    }
    Ok(BoundedProcessResult::default())
}

pub const PUBLIC_EXPORTS: &[&str] = &["BoundedProcessResult", "ProcessOutputLimitError", "run_bounded_process"];
