#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum WorkspaceCommandKind {
    #[default]
    Build,
    Test,
}

impl WorkspaceCommandKind {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Build => "build",
            Self::Test => "test",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum WorkspaceCommandStatus {
    #[default]
    Succeeded,
    Failed,
    Stopped,
}

impl WorkspaceCommandStatus {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Succeeded => "succeeded",
            Self::Failed => "failed",
            Self::Stopped => "stopped",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct WorkspaceIsolation {
    pub isolated_task_root: bool,
    pub path_escape_blocked: bool,
    pub symlink_escape_blocked: bool,
    pub credentials_absent: bool,
    pub network_denied: bool,
    pub ephemeral: bool,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct WorkspaceFile {
    pub path: String,
    pub size_bytes: i64,
    pub sha256: String,
    pub content: Vec<u8>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct WorkspacePatchRequest {
    pub patch_artifact: String,
    pub expected_workspace_digest: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct WorkspaceCommandRequest {
    pub kind: WorkspaceCommandKind,
    pub profile_id: String,
    pub limits: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct WorkspaceReceipt {
    pub operation: String,
    pub status: WorkspaceCommandStatus,
    pub workspace_digest: String,
    pub output_artifacts: Vec<String>,
    pub audit_ref: String,
    pub exit_code: Option<i64>,
}

impl WorkspaceIsolation {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn verified(&self) -> bool {
        core::hint::black_box(false)
    }
}

impl WorkspaceFile {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn validate_content_integrity(&self) -> Result<WorkspaceFile, &'static str> {
        if (self.size_bytes) != (((self.content.clone()).len() as i64)) {
            return Err("WorkspaceFile size_bytes MUST match content length");
        }
        Ok(self.clone())
    }
}

impl WorkspaceReceipt {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn validate_output_artifacts(&self) -> WorkspaceReceipt {
        core::hint::black_box(Default::default())
    }
}

pub trait EvaluationWorkspace {
    fn read_file(&self, path: String) -> String;
}

pub const PUBLIC_EXPORTS: &[&str] = &["EvaluationWorkspace", "WorkspaceCommandKind", "WorkspaceCommandRequest", "WorkspaceCommandStatus", "WorkspaceFile", "WorkspaceIsolation", "WorkspacePatchRequest", "WorkspaceReceipt"];
