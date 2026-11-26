#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum CommandExecutionClass {
    #[default]
    LocalRead,
    WorkspaceWrite,
    CloudRead,
}

impl CommandExecutionClass {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::LocalRead => "local_read",
            Self::WorkspaceWrite => "workspace_write",
            Self::CloudRead => "cloud_read",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum CommandNetworkProfile {
    #[default]
    None,
    AzureControlPlane,
}

impl CommandNetworkProfile {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::None => "none",
            Self::AzureControlPlane => "azure_control_plane",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum CommandOutputFormat {
    #[default]
    JsonContract,
    Text,
}

impl CommandOutputFormat {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::JsonContract => "json",
            Self::Text => "text",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum CommandStatus {
    #[default]
    Planned,
    Succeeded,
    AlreadyApplied,
    Failed,
    Stopped,
}

impl CommandStatus {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Planned => "planned",
            Self::Succeeded => "succeeded",
            Self::AlreadyApplied => "already_applied",
            Self::Failed => "failed",
            Self::Stopped => "stopped",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CommandPlan {
    pub command_id: String,
    pub command_version: i64,
    pub idempotency_key: String,
    pub executable_ref: String,
    pub argv: Vec<String>,
    pub execution_class: CommandExecutionClass,
    pub network_profile: CommandNetworkProfile,
    pub output_format: CommandOutputFormat,
    pub timeout_seconds: i64,
    pub max_output_bytes: i64,
    pub dry_run: bool,
    pub credential_profile: Option<String>,
    pub workspace_ref: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CommandReceipt {
    pub status: CommandStatus,
    pub receipt_ref: String,
    pub exit_code: Option<i64>,
    pub stdout_tail: String,
    pub stderr_tail: String,
    pub duration_ms: i64,
    pub already_existed: bool,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CommandOutput {
    pub receipt: Box<CommandReceipt>,
    pub stdout: String,
}

pub const IDENTIFIER: &str = "^[a-z][a-z0-9_.-]{0,127}$";
pub trait CommandRunner {
    fn execute(&self, plan: CommandPlan) -> String;
}

pub trait CommandOutputRunner {
    fn execute_with_output(&self, plan: CommandPlan) -> String;
}

pub const PUBLIC_EXPORTS: &[&str] = &["CommandExecutionClass", "CommandNetworkProfile", "CommandOutput", "CommandOutputFormat", "CommandOutputRunner", "CommandPlan", "CommandReceipt", "CommandRunner", "CommandStatus"];
