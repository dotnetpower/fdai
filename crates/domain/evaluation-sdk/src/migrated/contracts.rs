#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum AuthorityCeiling {
    #[default]
    Shadow,
    Hil,
    Enforce,
}

impl AuthorityCeiling {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Shadow => "shadow",
            Self::Hil => "hil",
            Self::Enforce => "enforce",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum SideEffectClass {
    #[default]
    Observe,
    Workspace,
    Substrate,
}

impl SideEffectClass {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Observe => "observe",
            Self::Workspace => "workspace",
            Self::Substrate => "substrate",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum EvaluationStatus {
    #[default]
    Completed,
    Held,
    Failed,
}

impl EvaluationStatus {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Completed => "completed",
            Self::Held => "held",
            Self::Failed => "failed",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum WorkspaceOperation {
    #[default]
    Read,
    Edit,
    Build,
    Test,
}

impl WorkspaceOperation {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Read => "read",
            Self::Edit => "edit",
            Self::Build => "build",
            Self::Test => "test",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum QualityGateStatus {
    #[default]
    NotRequired,
    Passed,
    Failed,
}

impl QualityGateStatus {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::NotRequired => "not_required",
            Self::Passed => "passed",
            Self::Failed => "failed",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct MetadataEntry {
    pub key: String,
    pub value: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Capability {
    pub capability_id: String,
    pub side_effect_class: SideEffectClass,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct TargetRef {
    pub kind: String,
    pub value: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ResourceLimits {
    pub cpu_seconds: i64,
    pub memory_bytes: i64,
    pub process_count: i64,
    pub output_bytes: i64,
    pub wall_clock_seconds: i64,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct WorkspacePolicy {
    pub operations: Vec<WorkspaceOperation>,
    pub max_files: i64,
    pub max_total_bytes: i64,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ArtifactPolicy {
    pub allowed_media_types: Vec<String>,
    pub max_artifact_bytes: i64,
    pub max_artifacts: i64,
    pub max_ttl_seconds: i64,
    pub allow_executable_outputs: bool,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct NetworkPolicy {
    pub deny_by_default: bool,
    pub allowed_origins: Vec<String>,
}

impl NetworkPolicy {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !self.deny_by_default { return Err("deny_by_default violated literal bool invariant"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct EvidenceRequirements {
    pub evidence_required: bool,
    pub terminal_audit_required: bool,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct EvaluationRequest {
    pub session_id: String,
    pub requester_id: String,
    pub purpose: String,
    pub requested_capabilities: Vec<Capability>,
    pub authority_ceiling: AuthorityCeiling,
    pub task_count_limit: i64,
    pub concurrency_limit: i64,
    pub deadline: String,
    pub workspace_policy: Box<WorkspacePolicy>,
    pub artifact_policy: Box<ArtifactPolicy>,
    pub network_policy: Box<NetworkPolicy>,
    pub evidence_requirements: Box<EvidenceRequirements>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ArtifactSpec {
    pub name: String,
    pub media_type: String,
    pub max_bytes: i64,
    pub ttl_seconds: i64,
    pub executable: bool,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ArtifactRef {
    pub artifact_id: String,
    pub session_id: String,
    pub task_id: String,
    pub name: String,
    pub media_type: String,
    pub size_bytes: i64,
    pub sha256: String,
    pub expires_at: String,
    pub executable: bool,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct EvaluationTask {
    pub session_id: String,
    pub task_id: String,
    pub correlation_key: Option<String>,
    pub phase: String,
    pub objective: String,
    pub target: Box<TargetRef>,
    pub input_artifacts: Vec<ArtifactRef>,
    pub expected_outputs: Vec<ArtifactSpec>,
    pub requested_capabilities: Vec<Capability>,
    pub deadline: String,
    pub resource_limits: Box<ResourceLimits>,
    pub metadata: Vec<MetadataEntry>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct DecisionReceipt {
    pub selected_tier: String,
    pub control_loop_outcome: String,
    pub decision: String,
    pub autonomy_mode: AuthorityCeiling,
    pub cited_rule_refs: Vec<String>,
    pub cited_evidence_refs: Vec<String>,
    pub action_refs: Vec<String>,
    pub rollback_refs: Vec<String>,
    pub verifier_passed: bool,
    pub quality_gate_status: QualityGateStatus,
    pub authority_ceiling: AuthorityCeiling,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct EvaluationResult {
    pub session_id: String,
    pub task_id: String,
    pub phase: String,
    pub status: EvaluationStatus,
    pub summary: String,
    pub output_artifacts: Vec<ArtifactRef>,
    pub evidence_refs: Vec<String>,
    pub terminal_audit_ref: String,
    pub decision_receipt: Box<DecisionReceipt>,
    pub reason_code: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ExternalValidationStage {
    pub stage_id: String,
    pub passed: bool,
    pub receipt_ref: Box<ArtifactRef>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ExternalValidationReceipt {
    pub session_id: String,
    pub task_id: String,
    pub trusted_for_execution: bool,
    pub stages: Vec<ExternalValidationStage>,
}

impl ExternalValidationReceipt {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.trusted_for_execution { return Err("trusted_for_execution violated literal bool invariant"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ContractModel {
    pub initialized: bool,
}

impl WorkspacePolicy {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn unique_operations(&self) -> Result<WorkspacePolicy, &'static str> {
        Err("runtime_binding_required")
    }
}

impl ArtifactPolicy {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn unique_media_types(&self) -> Result<ArtifactPolicy, &'static str> {
        if (self.allowed_media_types.clone()).is_empty() {
            return Err("allowed_media_types MUST contain at least one media type");
        }
        if ((((self.allowed_media_types.clone()).into_iter().collect::<std::collections::BTreeSet<String>>()).len() as i64)) != (((self.allowed_media_types.clone()).len() as i64)) {
            return Err("allowed_media_types MUST be unique");
        }
        Ok(self.clone())
    }
}

impl NetworkPolicy {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn unique_origins(&self) -> NetworkPolicy {
        core::hint::black_box(Default::default())
    }
}

impl EvaluationRequest {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn unique_capabilities(&self) -> Result<EvaluationRequest, &'static str> {
        Err("runtime_binding_required")
    }
}

impl EvaluationTask {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn validate_collections(&self) -> Result<EvaluationTask, &'static str> {
        Err("runtime_binding_required")
    }
}

impl DecisionReceipt {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn validate_collections(&self) -> DecisionReceipt {
        core::hint::black_box(Default::default())
    }
}

impl EvaluationResult {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn validate_outputs(&self) -> Result<EvaluationResult, &'static str> {
        Err("runtime_binding_required")
    }
}

impl ExternalValidationReceipt {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn validate_stages(&self) -> Result<ExternalValidationReceipt, &'static str> {
        Err("runtime_binding_required")
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["ArtifactPolicy", "ArtifactRef", "ArtifactSpec", "AuthorityCeiling", "Capability", "ContractModel", "DecisionReceipt", "EvaluationRequest", "EvaluationResult", "EvaluationStatus", "EvaluationTask", "EvidenceRequirements", "ExternalValidationReceipt", "ExternalValidationStage", "MetadataEntry", "NetworkPolicy", "QualityGateStatus", "ResourceLimits", "SideEffectClass", "TargetRef", "WorkspaceOperation", "WorkspacePolicy"];
