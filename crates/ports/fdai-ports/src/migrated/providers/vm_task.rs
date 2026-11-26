use std::collections::BTreeMap;
#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum PythonTaskCapability {
    #[default]
    Gpu,
    Network,
    FilesystemRead,
    FilesystemWrite,
    Process,
}

impl PythonTaskCapability {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Gpu => "gpu",
            Self::Network => "network",
            Self::FilesystemRead => "filesystem_read",
            Self::FilesystemWrite => "filesystem_write",
            Self::Process => "process",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum VmTaskStatus {
    #[default]
    Planned,
    Submitted,
    Running,
    Succeeded,
    Failed,
    Cancelled,
}

impl VmTaskStatus {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Planned => "planned",
            Self::Submitted => "submitted",
            Self::Running => "running",
            Self::Succeeded => "succeeded",
            Self::Failed => "failed",
            Self::Cancelled => "cancelled",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct PythonTaskFile {
    pub path: String,
    pub content: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct PythonTaskSpec {
    pub task_id: String,
    pub version: String,
    pub entrypoint: String,
    pub files: Vec<PythonTaskFile>,
    pub required_modules: Vec<String>,
    pub capabilities: Vec<PythonTaskCapability>,
    pub timeout_seconds: i64,
    pub python_executable: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct VmTaskTarget {
    pub resource_ref: String,
    pub provider_ref: Option<String>,
    pub capabilities: Vec<PythonTaskCapability>,
    pub os_type: String,
    pub location: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct VmTaskRequest {
    pub idempotency_key: String,
    pub task: Box<PythonTaskSpec>,
    pub target: Box<VmTaskTarget>,
    pub inputs: BTreeMap<String, String>,
    pub dry_run: bool,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct VmTaskReceipt {
    pub run_ref: String,
    pub artifact_hash: String,
    pub status: VmTaskStatus,
    pub detail: String,
    pub already_existed: bool,
    pub exit_code: Option<i64>,
    pub stdout_tail: String,
    pub stderr_tail: String,
}

pub const TASK_ID: &str = "^[a-z][a-z0-9_.-]{0,79}$";
pub const MODULE: &str = "^[A-Za-z_][A-Za-z0-9_.]{0,127}$";
impl PythonTaskFile {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn sha256(&self) -> String {
        core::hint::black_box(String::new())
    }
}

impl PythonTaskSpec {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn artifact_hash(&self) -> String {
        let payload: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("task_id"), self.task_id.clone()), (String::from("version"), self.version.clone()), (String::from("entrypoint"), self.entrypoint.clone()), (String::from("files"), String::new()), (String::from("required_modules"), String::new()), (String::from("capabilities"), String::new()), (String::from("timeout_seconds"), String::new()), (String::from("python_executable"), self.python_executable.clone())]);
        String::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn artifact_ref(&self) -> String {
        core::hint::black_box(String::new())
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct VmTaskRunnerError {
    pub message: String,
}

impl VmTaskRunnerError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for VmTaskRunnerError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for VmTaskRunnerError {}

pub trait PythonTaskArtifactStore {
    fn put(&self, task: PythonTaskSpec, created_by: String) -> String;
}

pub trait VmTaskTargetResolver {
    fn resolve(&self, resource_ref: String) -> String;
}

pub trait VmTaskRunner {
    fn run(&self, request: VmTaskRequest) -> String;
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn validate_python_task_artifact_ref(mut value: String) -> Result<String, &'static str> {
    Ok(value.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn python_task_to_mapping(mut task: PythonTaskSpec) -> std::collections::BTreeMap<String, String> {
    std::collections::BTreeMap::from([(String::from("task_id"), task.task_id.clone()), (String::from("version"), task.version.clone()), (String::from("entrypoint"), task.entrypoint.clone()), (String::from("files"), String::new()), (String::from("required_modules"), String::new()), (String::from("capabilities"), String::new()), (String::from("timeout_seconds"), String::new()), (String::from("python_executable"), task.python_executable.clone())])
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn python_task_from_mapping(mut value: std::collections::BTreeMap<String, String>) -> Result<PythonTaskSpec, &'static str> {
    let files_value: Option<String> = (value.clone()).get("files").cloned();
    if !(true) {
        return Err("Python task files MUST be an array");
    }
    let mut files: Vec<PythonTaskFile> = Vec::<PythonTaskFile>::new();
    Ok(PythonTaskSpec { files: files.clone(), ..Default::default() })
}

pub const PUBLIC_EXPORTS: &[&str] = &["PythonTaskCapability", "PythonTaskArtifactStore", "PythonTaskFile", "PythonTaskSpec", "VmTaskReceipt", "VmTaskRequest", "VmTaskRunner", "VmTaskRunnerError", "VmTaskStatus", "VmTaskTarget", "VmTaskTargetResolver", "python_task_from_mapping", "python_task_to_mapping", "validate_python_task_artifact_ref"];
