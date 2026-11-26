#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum SandboxBackend {
    #[default]
    Bubblewrap,
    VmTask,
}

impl SandboxBackend {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Bubblewrap => "bubblewrap",
            Self::VmTask => "vm_task",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum WorkspaceAccess {
    #[default]
    None,
    ReadOnly,
    ReadWrite,
}

impl WorkspaceAccess {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::None => "none",
            Self::ReadOnly => "read_only",
            Self::ReadWrite => "read_write",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct SandboxProfile {
    pub profile_id: String,
    pub backend: SandboxBackend,
    pub command_ids: Vec<String>,
    pub execution_classes: Vec<String>,
    pub network_profiles: Vec<String>,
    pub workspace_access: WorkspaceAccess,
    pub max_timeout_seconds: i64,
    pub max_output_bytes: i64,
    pub allow_credentials: bool,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct VmTaskSandboxProfile {
    pub profile_id: String,
    pub task_ids: Vec<String>,
    pub allowed_capabilities: Vec<String>,
    pub max_timeout_seconds: i64,
    pub max_input_items: i64,
    pub max_input_bytes: i64,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ToolSandboxProfile {
    pub profile_id: String,
    pub action_type_names: Vec<String>,
    pub allowed_modes: Vec<String>,
    pub max_argument_items: i64,
    pub max_argument_bytes: i64,
    pub max_tool_ref_bytes: i64,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ProgrammaticPipelineSandboxProfile {
    pub profile_id: String,
    pub allowed_read_tools: Vec<String>,
    pub max_timeout_seconds: f64,
    pub max_input_items: i64,
    pub max_input_bytes: i64,
    pub max_tool_calls: i64,
    pub max_call_input_bytes: i64,
    pub max_call_output_bytes: i64,
    pub max_stdout_bytes: i64,
    pub max_stderr_bytes: i64,
    pub max_final_json_bytes: i64,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct DocumentConverterSandboxProfile {
    pub profile_id: String,
    pub converter_ids: Vec<String>,
    pub allowed_suffixes: Vec<String>,
    pub max_input_bytes: i64,
    pub max_output_bytes: i64,
}

pub const PROFILE_ID: &str = "^[a-z][a-z0-9.-]{2,127}$";
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct SandboxPolicyError {
    pub message: String,
}

impl SandboxPolicyError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for SandboxPolicyError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for SandboxPolicyError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct SandboxProfileCatalog {
    pub initialized: bool,
}

impl SandboxProfileCatalog {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn register(&self, mut profile: SandboxProfile) -> String {
        if !self.initialized {
            return String::new();
        }
        String::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn list(&self) -> Vec<SandboxProfile> {
        if !self.initialized {
            return Vec::new();
        }
        Vec::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn require(&self, mut command_id: String) -> Result<SandboxProfile, &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn constrain(&self, mut plan: String) -> Result<String, &'static str> {
        let profile: SandboxProfile = self.require(String::new()).unwrap_or_else(|_| Default::default());
        Ok(String::new())
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ProfiledCommandRunner {
    pub initialized: bool,
}

impl ProfiledCommandRunner {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn execute(&self, mut plan: String) -> String {
        if !self.initialized {
            return String::new();
        }
        String::new()
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct VmTaskSandboxCatalog {
    pub initialized: bool,
}

impl VmTaskSandboxCatalog {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn register(&self, mut profile: VmTaskSandboxProfile) -> String {
        if !self.initialized {
            return String::new();
        }
        String::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn list(&self) -> Vec<VmTaskSandboxProfile> {
        if !self.initialized {
            return Vec::new();
        }
        Vec::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn require(&self, mut task_id: String) -> Result<VmTaskSandboxProfile, &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn constrain(&self, mut request: String) -> Result<String, &'static str> {
        let profile: VmTaskSandboxProfile = self.require(String::new()).unwrap_or_else(|_| Default::default());
        Ok(String::new())
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ProfiledVmTaskRunner {
    pub initialized: bool,
}

impl ProfiledVmTaskRunner {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn run(&self, mut request: String) -> String {
        if !self.initialized {
            return String::new();
        }
        String::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn status(&self, mut run_ref: String) -> String {
        if !self.initialized {
            return String::new();
        }
        String::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn cancel(&self, mut run_ref: String) -> String {
        if !self.initialized {
            return String::new();
        }
        String::new()
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ToolSandboxCatalog {
    pub initialized: bool,
}

impl ToolSandboxCatalog {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn register(&self, mut profile: ToolSandboxProfile) -> String {
        if !self.initialized {
            return String::new();
        }
        String::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn list(&self) -> Vec<ToolSandboxProfile> {
        if !self.initialized {
            return Vec::new();
        }
        Vec::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn require(&self, mut action_type_name: String) -> Result<ToolSandboxProfile, &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn constrain(&self, mut request: String) -> Result<String, &'static str> {
        let profile: ToolSandboxProfile = self.require(String::new()).unwrap_or_else(|_| Default::default());
        Ok(request.clone())
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ProfiledToolExecutor {
    pub initialized: bool,
}

impl ProfiledToolExecutor {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn execute(&self, mut request: String) -> String {
        if !self.initialized {
            return String::new();
        }
        String::new()
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ProgrammaticPipelineSandboxCatalog {
    pub initialized: bool,
}

impl ProgrammaticPipelineSandboxCatalog {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn constrain(&self, mut request: String) -> Result<String, &'static str> {
        Ok(request.clone())
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct DocumentConverterSandboxCatalog {
    pub initialized: bool,
}

impl DocumentConverterSandboxCatalog {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn register(&self, mut profile: DocumentConverterSandboxProfile) -> String {
        if !self.initialized {
            return String::new();
        }
        String::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn list(&self) -> Vec<DocumentConverterSandboxProfile> {
        if !self.initialized {
            return Vec::new();
        }
        Vec::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn constrain(&self, mut request: String) -> Result<String, &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ProfiledDocumentConverter {
    pub initialized: bool,
}

impl ProfiledDocumentConverter {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn convert(&self, mut request: String) -> Result<String, &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["DocumentConverterSandboxCatalog", "DocumentConverterSandboxProfile", "ProfiledCommandRunner", "ProfiledDocumentConverter", "ProfiledToolExecutor", "ProfiledVmTaskRunner", "ProgrammaticPipelineSandboxCatalog", "ProgrammaticPipelineSandboxProfile", "SandboxBackend", "SandboxPolicyError", "SandboxProfile", "SandboxProfileCatalog", "ToolSandboxCatalog", "ToolSandboxProfile", "VmTaskSandboxCatalog", "VmTaskSandboxProfile", "WorkspaceAccess"];
