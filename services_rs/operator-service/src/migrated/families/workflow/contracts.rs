use std::collections::BTreeMap;
#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum WorkflowOperation {
    #[default]
    RuleList,
    RuleSearch,
    RuleFindingsSummary,
    RuleFindings,
    RuleDetail,
    RuleActivationStatus,
    RuleActivationHistory,
    RuleActivationRequest,
    RuleActivationApprove,
    BestPracticeList,
    BestPracticeDetail,
    CafList,
    CafDetail,
    WaraList,
    WaraDetail,
    McsbList,
    McsbDetail,
    MsrcCsafList,
    MsrcCsafDetail,
    PromotionGateList,
    ContextSelectionComparisonList,
    WorkflowActionTypeList,
    WorkflowValidate,
    WorkflowCatalog,
    WorkflowRunRequest,
    WorkflowResumeRequest,
    WorkflowCancelRequest,
    WorkflowRetryRequest,
    PythonCapabilities,
    PythonGenerate,
    PythonValidate,
    PythonStageProposal,
    PythonTest,
    PythonRunProposal,
    PythonScheduleProposal,
    SkillSourceBrowse,
    SkillSourceSearch,
    SkillSourceInspect,
    SkillSourceCheckUpdate,
    SkillSourceCandidates,
    SkillSourceApprovalProposal,
    SkillSourceRevocationProposal,
    TrajectoryDatasetList,
    TrajectoryDatasetDetail,
    WorkflowDefinitionList,
    WorkflowDefinitionCreateProposal,
    WorkflowBindingCreateProposal,
    WorkflowBindingUpdateProposal,
    WorkflowBindingDeleteProposal,
}

impl WorkflowOperation {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::RuleList => "rule.list",
            Self::RuleSearch => "rule.search",
            Self::RuleFindingsSummary => "rule.findings-summary",
            Self::RuleFindings => "rule.findings",
            Self::RuleDetail => "rule.detail",
            Self::RuleActivationStatus => "rule.activation-status",
            Self::RuleActivationHistory => "rule.activation-history",
            Self::RuleActivationRequest => "rule.activation-request",
            Self::RuleActivationApprove => "rule.activation-approve",
            Self::BestPracticeList => "best-practice.list",
            Self::BestPracticeDetail => "best-practice.detail",
            Self::CafList => "caf.list",
            Self::CafDetail => "caf.detail",
            Self::WaraList => "wara.list",
            Self::WaraDetail => "wara.detail",
            Self::McsbList => "mcsb.list",
            Self::McsbDetail => "mcsb.detail",
            Self::MsrcCsafList => "msrc-csaf.list",
            Self::MsrcCsafDetail => "msrc-csaf.detail",
            Self::PromotionGateList => "promotion-gate.list",
            Self::ContextSelectionComparisonList => "context-selection.comparison-list",
            Self::WorkflowActionTypeList => "workflow.action-type-list",
            Self::WorkflowValidate => "workflow.validate",
            Self::WorkflowCatalog => "workflow.catalog",
            Self::WorkflowRunRequest => "workflow.run-request",
            Self::WorkflowResumeRequest => "workflow.resume-request",
            Self::WorkflowCancelRequest => "workflow.cancel-request",
            Self::WorkflowRetryRequest => "workflow.retry-request",
            Self::PythonCapabilities => "python-task.capabilities",
            Self::PythonGenerate => "python-task.generate",
            Self::PythonValidate => "python-task.validate",
            Self::PythonStageProposal => "python-task.stage-proposal",
            Self::PythonTest => "python-task.test",
            Self::PythonRunProposal => "python-task.run-proposal",
            Self::PythonScheduleProposal => "python-task.schedule-proposal",
            Self::SkillSourceBrowse => "skill-source.browse",
            Self::SkillSourceSearch => "skill-source.search",
            Self::SkillSourceInspect => "skill-source.inspect",
            Self::SkillSourceCheckUpdate => "skill-source.check-update",
            Self::SkillSourceCandidates => "skill-source.candidates",
            Self::SkillSourceApprovalProposal => "skill-source.approval-proposal",
            Self::SkillSourceRevocationProposal => "skill-source.revocation-proposal",
            Self::TrajectoryDatasetList => "trajectory-dataset.list",
            Self::TrajectoryDatasetDetail => "trajectory-dataset.detail",
            Self::WorkflowDefinitionList => "workflow-definition.list",
            Self::WorkflowDefinitionCreateProposal => "workflow-definition.create-proposal",
            Self::WorkflowBindingCreateProposal => "workflow-binding.create-proposal",
            Self::WorkflowBindingUpdateProposal => "workflow-binding.update-proposal",
            Self::WorkflowBindingDeleteProposal => "workflow-binding.delete-proposal",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ProjectionProvenance {
    pub source_ref: String,
    pub revision: String,
    pub synthetic: bool,
}

impl ProjectionProvenance {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.source_ref.trim().is_empty() { return Err("source_ref must be non-empty"); }
        if self.revision.trim().is_empty() { return Err("revision must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct WorkflowReadRequest {
    pub operation: WorkflowOperation,
    pub principal_id: String,
    pub query: BTreeMap<String, String>,
    pub path_parameters: BTreeMap<String, String>,
    pub body: Option<String>,
    pub limit: Option<i64>,
    pub offset: Option<i64>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct WorkflowReadResult {
    pub payload: String,
    pub provenance: Box<ProjectionProvenance>,
    pub status_code: i64,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct WorkflowProposal {
    pub operation: WorkflowOperation,
    pub principal_id: String,
    pub idempotency_key: String,
    pub expected_revision: String,
    pub request_source: String,
    pub path_parameters: BTreeMap<String, String>,
    pub payload: String,
    pub mode: String,
    pub principal_roles: Vec<String>,
}

impl WorkflowProposal {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.principal_id.trim().is_empty() { return Err("principal_id must be non-empty"); }
        if self.idempotency_key.trim().is_empty() { return Err("idempotency_key must be non-empty"); }
        if self.expected_revision.trim().is_empty() { return Err("expected_revision must be non-empty"); }
        if self.request_source.trim().is_empty() { return Err("request_source must be non-empty"); }
        if self.payload.trim().is_empty() { return Err("payload must be non-empty"); }
        if self.mode.trim().is_empty() { return Err("mode must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct WorkflowProposalReceipt {
    pub proposal_id: String,
    pub revision: String,
    pub duplicate: bool,
}

impl WorkflowProposalReceipt {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.proposal_id.trim().is_empty() { return Err("proposal_id must be non-empty"); }
        if self.revision.trim().is_empty() { return Err("revision must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct WorkflowMutationRequest {
    pub operation: WorkflowOperation,
    pub principal_id: String,
    pub idempotency_key: String,
    pub expected_revision: String,
    pub path_parameters: BTreeMap<String, String>,
    pub payload: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct WorkflowMutationResult {
    pub payload: String,
    pub revision: String,
    pub status_code: i64,
}

pub trait WorkflowReadStore {
    fn read(&self, request: WorkflowReadRequest) -> String;
}

pub trait WorkflowProposalWriter {
    fn submit(&self, proposal: WorkflowProposal) -> String;
}

pub trait WorkflowMutationWriter {
    fn mutate(&self, request: WorkflowMutationRequest) -> String;
}

pub trait WorkflowPrincipalAuthorizer {
    fn call(&self, request: String, required_roles: std::collections::BTreeSet<String>) -> String;
}

pub const PUBLIC_EXPORTS: &[&str] = &["ProjectionProvenance", "WorkflowOperation", "WorkflowMutationRequest", "WorkflowMutationResult", "WorkflowMutationWriter", "WorkflowPrincipalAuthorizer", "WorkflowProposal", "WorkflowProposalReceipt", "WorkflowProposalWriter", "WorkflowReadRequest", "WorkflowReadResult", "WorkflowReadStore"];
