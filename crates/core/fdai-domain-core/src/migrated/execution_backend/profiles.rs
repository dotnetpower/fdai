#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ExecutionBackendKind {
    #[default]
    Bubblewrap,
    VmTask,
    AzureContainerAppsJob,
}

impl ExecutionBackendKind {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Bubblewrap => "bubblewrap",
            Self::VmTask => "vm_task",
            Self::AzureContainerAppsJob => "azure_container_apps_job",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum WorkspaceMode {
    #[default]
    None,
    ReadOnly,
    ReadWrite,
}

impl WorkspaceMode {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::None => "none",
            Self::ReadOnly => "read_only",
            Self::ReadWrite => "read_write",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ExecutionNetworkProfile {
    #[default]
    None,
    AzureControlPlane,
}

impl ExecutionNetworkProfile {
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
pub enum PersistenceMode {
    #[default]
    Ephemeral,
    Durable,
}

impl PersistenceMode {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Ephemeral => "ephemeral",
            Self::Durable => "durable",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum CancellationGuarantee {
    #[default]
    None,
    BestEffort,
    Confirmed,
}

impl CancellationGuarantee {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::None => "none",
            Self::BestEffort => "best_effort",
            Self::Confirmed => "confirmed",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ResourceCeilings {
    pub cpu_millis: i64,
    pub memory_bytes: i64,
    pub ephemeral_storage_bytes: i64,
    pub max_concurrency: i64,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ExecutionAuthority {
    pub backend_kind: ExecutionBackendKind,
    pub workload_ids: Vec<String>,
    pub workspace_mode: WorkspaceMode,
    pub network_profiles: Vec<ExecutionNetworkProfile>,
    pub credential_profile_refs: Vec<String>,
    pub max_timeout_seconds: i64,
    pub max_output_bytes: i64,
    pub resources: Box<ResourceCeilings>,
    pub regions: Vec<String>,
    pub scope_refs: Vec<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ExecutionBackendProfile {
    pub profile_id: String,
    pub version: String,
    pub backend_kind: ExecutionBackendKind,
    pub workload_ids: Vec<String>,
    pub workspace_mode: WorkspaceMode,
    pub network_profiles: Vec<ExecutionNetworkProfile>,
    pub credential_profile_refs: Vec<String>,
    pub max_timeout_seconds: i64,
    pub max_output_bytes: i64,
    pub resources: Box<ResourceCeilings>,
    pub persistence_mode: PersistenceMode,
    pub regions: Vec<String>,
    pub scope_refs: Vec<String>,
    pub cancellation_guarantee: CancellationGuarantee,
    pub template_ref: Option<String>,
    pub artifact_digest: Option<String>,
}

pub const IDENTIFIER: &str = "^[a-z][a-z0-9_.-]{0,127}$";
pub const VERSION: &str = "^[0-9]+\\.[0-9]+\\.[0-9]+$";
pub const DIGEST: &str = "^[0-9a-f]{64}$";
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ExecutionProfileError {
    pub message: String,
}

impl ExecutionProfileError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for ExecutionProfileError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for ExecutionProfileError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ExecutionBackendProfileRegistry {
    pub initialized: bool,
}

impl ExecutionBackendProfileRegistry {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn list(&self) -> Vec<ExecutionBackendProfile> {
        if !self.initialized {
            return Vec::new();
        }
        Vec::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn select_enabled(&self, mut profile_ids: std::collections::BTreeSet<String>) -> String {
        if !self.initialized {
            return String::new();
        }
        String::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn require(&self, mut profile_id: String) -> Result<ExecutionBackendProfile, &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn require_enabled(&self, mut profile_id: String) -> Result<ExecutionBackendProfile, &'static str> {
        let profile: ExecutionBackendProfile = self.require(profile_id.clone()).unwrap_or_else(|_| Default::default());
        Ok(profile.clone())
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn validate_envelope(mut value: String) -> Result<(), &'static str> {
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn intersect_execution_profile(mut authority: ExecutionAuthority, mut profile: ExecutionBackendProfile) -> Result<ExecutionBackendProfile, &'static str> {
    let _ = require_subset(std::collections::BTreeSet::new(), std::collections::BTreeSet::new(), String::from("workload")).unwrap_or_else(|_| ());
    let _ = require_subset(std::collections::BTreeSet::new(), std::collections::BTreeSet::new(), String::from("network")).unwrap_or_else(|_| ());
    let _ = require_subset(std::collections::BTreeSet::new(), std::collections::BTreeSet::new(), String::from("credential")).unwrap_or_else(|_| ());
    let _ = require_subset(std::collections::BTreeSet::new(), std::collections::BTreeSet::new(), String::from("region")).unwrap_or_else(|_| ());
    let _ = require_subset(std::collections::BTreeSet::new(), std::collections::BTreeSet::new(), String::from("scope")).unwrap_or_else(|_| ());
    if (profile.max_timeout_seconds) > (authority.max_timeout_seconds) {
        return Err("backend profile would widen timeout authority");
    }
    if (profile.max_output_bytes) > (authority.max_output_bytes) {
        return Err("backend profile would widen output authority");
    }
    if resources_widen(*(profile.resources.clone()), *(authority.resources.clone())) {
        return Err("backend profile would widen resource authority");
    }
    Ok(profile.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn require_subset(mut left: std::collections::BTreeSet<String>, mut right: std::collections::BTreeSet<String>, mut name: String) -> Result<(), &'static str> {
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn resources_widen(mut left: ResourceCeilings, mut right: ResourceCeilings) -> bool {
    ((left.cpu_millis) > (right.cpu_millis)) || (((left.memory_bytes) > (right.memory_bytes)) || (((left.ephemeral_storage_bytes) > (right.ephemeral_storage_bytes)) || ((left.max_concurrency) > (right.max_concurrency))))
}

pub const PUBLIC_EXPORTS: &[&str] = &["CancellationGuarantee", "ExecutionAuthority", "ExecutionBackendKind", "ExecutionBackendProfile", "ExecutionBackendProfileRegistry", "ExecutionNetworkProfile", "ExecutionProfileError", "PersistenceMode", "ResourceCeilings", "WorkspaceMode", "intersect_execution_profile"];
