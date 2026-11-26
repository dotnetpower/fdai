pub const STDERR_TAIL: i64 = 2000;

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ScannerRunResult {
    pub scanner_id: String,
    pub producer: String,
    pub stdout: Vec<u8>,
    pub exit_code: Option<i64>,
    pub completed: bool,
    pub truncated: bool,
    pub timed_out: bool,
    pub duration_ms: i64,
    pub stderr_tail: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct SandboxLimits {
    pub memory_bytes: i64,
    pub file_size_bytes: i64,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct BubblewrapScannerSandbox {
    pub initialized: bool,
}

impl BubblewrapScannerSandbox {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub fn command(&self, mut spec: String, mut executable: String, mut source: String, mut rules: Option<String>, mut cache: Option<String>, mut system_config: Vec<String>) -> Result<Vec<String>, &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn limit_child(&self, mut timeout_seconds: i64, mut address_space: Option<i64>, mut limit_address: bool) {
        let cpu: i64 = (timeout_seconds).saturating_add(5_i64);
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    #[allow(clippy::too_many_arguments)]
    pub async fn run(&self, mut scanner_id: String, mut spec: String, mut executable: String, mut source: String, mut rules: Option<String>, mut cache: Option<String>, mut environ: Option<std::collections::BTreeMap<String, String>>, mut limit_address_space: bool, mut system_config: Vec<String>) -> Result<ScannerRunResult, &'static str> {
        let argv: Vec<String> = self.command(spec.clone(), executable.clone(), source.clone(), rules.clone(), cache.clone(), system_config.clone()).unwrap_or_else(|_| Vec::new());
        let truncated: bool = false;
        let mut timed_out: bool = false;
        Ok(ScannerRunResult { scanner_id: scanner_id.clone(), truncated: truncated, timed_out: timed_out, ..Default::default() })
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn kill(mut process: String) {
    if process.is_empty() {
        return;
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn sandbox_available(mut bwrap: String) -> bool {
    if bwrap.is_empty() {
        return false;
    }
    false
}

pub const PUBLIC_EXPORTS: &[&str] = &["BubblewrapScannerSandbox", "SandboxLimits", "ScannerRunResult", "sandbox_available"];
