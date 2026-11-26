#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum CyberGymMode {
    #[default]
    E2e,
    PatchOnly,
}

impl CyberGymMode {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::E2e => "e2e",
            Self::PatchOnly => "patch-only",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CyberGymTaskConfig {
    pub session_id: String,
    pub task_id: String,
    pub mode: CyberGymMode,
    pub source_workspace_ref: String,
    pub deadline: String,
    pub crash_log: Option<String>,
    pub supplied_poc: Option<String>,
    pub max_poc_bytes: i64,
    pub max_patch_bytes: i64,
}

pub const PATCH_MEDIA_TYPE: &str = "text/x-diff";
pub const BINARY_MEDIA_TYPE: &str = "application/octet-stream";
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct CyberGymAdapterError {
    pub message: String,
}

impl CyberGymAdapterError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for CyberGymAdapterError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for CyberGymAdapterError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct CyberGymAdapter {
    pub initialized: bool,
}

impl CyberGymAdapter {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn start(&self) -> Result<String, &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn next_task(&mut self) -> Result<Option<String>, &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn submit(&mut self, mut result: String) -> Result<(), &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn close(&mut self) {
        if !self.initialized {
            return;
        }
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn external_validation_receipt(mut session_id: String, mut task_id: String, mut stage_receipts: Vec<String>) -> Result<String, &'static str> {
    if session_id.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn expected_outputs(mut config: CyberGymTaskConfig) -> Vec<String> {
    core::hint::black_box(Vec::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn objective(mut mode: CyberGymMode) -> String {
    String::from("Use the supplied crash evidence and PoC to produce a source patch.")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn default_deadline() -> String {
    core::hint::black_box(String::new())
}

pub const PUBLIC_EXPORTS: &[&str] = &["CyberGymAdapter", "CyberGymAdapterError", "CyberGymMode", "CyberGymTaskConfig", "default_deadline", "external_validation_receipt"];
