use std::collections::BTreeMap;
pub const MAX_HIL_IDEMPOTENCY_KEY_CHARS: i64 = 1024;

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum HilApprovalDecision {
    #[default]
    Approve,
    Reject,
}

impl HilApprovalDecision {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Approve => "approve",
            Self::Reject => "reject",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct IamPrincipal {
    pub oid: String,
    pub roles: Vec<String>,
    pub username: Option<String>,
    pub principal_kind: String,
}

impl IamPrincipal {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.oid.trim().is_empty() { return Err("oid must be non-empty"); }
        if self.principal_kind.trim().is_empty() { return Err("principal_kind must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct AccessGrantRecord {
    pub request_id: String,
    pub correlation_id: String,
    pub capability_id: String,
    pub scope_ref: String,
    pub grant_mode: String,
    pub requested_at: String,
    pub expires_at: String,
    pub quorum: i64,
    pub status: String,
    pub revision: i64,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct AccessGrantSnapshotQuery {
    pub reviewer_ref: String,
    pub reviewer_roles: Vec<String>,
    pub after_sequence: Option<i64>,
    pub limit: i64,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct AccessGrantSnapshot {
    pub sequence: i64,
    pub generated_at: String,
    pub requests: Vec<AccessGrantRecord>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct AccessGrantDecisionCommand {
    pub request_id: String,
    pub reviewer_ref: String,
    pub reviewer_roles: Vec<String>,
    pub decision: String,
    pub reason: String,
    pub expected_revision: i64,
    pub decided_at: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct AccessGrantDecisionResult {
    pub request_id: String,
    pub status: String,
    pub revision: i64,
    pub approved_count: i64,
    pub quorum: i64,
    pub reviewed_at: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct DirectoryIdentity {
    pub provider: String,
    pub subject_id: String,
    pub username: String,
    pub display_name: Option<String>,
    pub active: bool,
    pub user_type: String,
    pub principal_type: String,
    pub roles: Vec<String>,
    pub group_ids: Vec<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct DirectoryStatus {
    pub source: String,
    pub availability: String,
    pub observed_at: Option<String>,
    pub detail: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct AccessRequestQuery {
    pub principal: Box<IamPrincipal>,
    pub limit: i64,
    pub offset: i64,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct AccessRequestCommand {
    pub principal: Box<IamPrincipal>,
    pub idempotency_key: String,
    pub identity_provider: String,
    pub target_subject_id: String,
    pub target_username: String,
    pub operation: String,
    pub role: String,
    pub justification: String,
    pub self_service: bool,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct AccessReviewCommand {
    pub principal: Box<IamPrincipal>,
    pub request_id: String,
    pub decision: String,
    pub justification: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct AssignmentCaseQuery {
    pub principal: Box<IamPrincipal>,
    pub limit: i64,
    pub offset: i64,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct AssignmentCreateCommand {
    pub principal: Box<IamPrincipal>,
    pub idempotency_key: String,
    pub subject_provider: String,
    pub subject_id: String,
    pub requested_role: String,
    pub duty_bindings: Vec<String>,
    pub goal_refs: Vec<String>,
    pub justification: String,
    pub revocation: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct AssignmentTransitionCommand {
    pub principal: Box<IamPrincipal>,
    pub case_id: String,
    pub expected_revision: i64,
    pub decision: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ReportingLineCaseQuery {
    pub principal: Box<IamPrincipal>,
    pub limit: i64,
    pub offset: i64,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ReportingLineCreateCommand {
    pub principal: Box<IamPrincipal>,
    pub idempotency_key: String,
    pub upload_id: String,
    pub candidate_id: String,
    pub effective_from: Option<String>,
    pub effective_until: Option<String>,
    pub supersedes_case_id: Option<String>,
    pub case_kind: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ReportingLineTransitionCommand {
    pub principal: Box<IamPrincipal>,
    pub case_id: String,
    pub expected_revision: i64,
    pub decision: String,
    pub edge_digest: String,
    pub case_kind: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct HandoverGoalCommand {
    pub principal: Box<IamPrincipal>,
    pub goal_id: String,
    pub operation: String,
    pub expected_revision: i64,
    pub reason_ref: Option<String>,
    pub evidence_ref: Option<String>,
    pub digest: Option<String>,
    pub kind: Option<String>,
    pub slot: Option<String>,
    pub source_goal_id: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ModelPreferenceCommand {
    pub principal_id: String,
    pub preferred_narrator_model: String,
    pub expected_revision: i64,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct WebSearchSettingsCommand {
    pub actor_id: String,
    pub enabled: bool,
    pub allowed_domains: Vec<String>,
    pub expected_revision: i64,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ModelBindingDraftCommand {
    pub actor_id: String,
    pub policy: String,
    pub policy_digest: String,
    pub expected_revision: i64,
    pub idempotency_key: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ModelBindingRequestCommand {
    pub actor_id: String,
    pub environment: String,
    pub policy_revision: i64,
    pub policy_digest: String,
    pub idempotency_key: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct DocumentOcrPolicyCommand {
    pub actor_id: String,
    pub policy: String,
    pub policy_digest: String,
    pub expected_revision: i64,
    pub idempotency_key: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct DocumentOcrPlanCommand {
    pub actor_id: String,
    pub environment: String,
    pub policy_revision: i64,
    pub policy_digest: String,
    pub idempotency_key: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct RuntimeSettingsCommand {
    pub actor_id: String,
    pub changes: String,
    pub expected_revision: i64,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct TeamsA1OnboardingPlanCommand {
    pub actor_id: String,
    pub environment: String,
    pub idempotency_key: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct TeamsWorkflowTestCommand {
    pub actor_id: String,
    pub request_id: String,
    pub webhook_url: String,
    pub channel_label: Option<String>,
    #[allow(clippy::type_complexity)]
    pub selected_channel_ids: Option<Vec<String>>,
    #[allow(clippy::type_complexity)]
    pub delivery_targets: Option<Vec<String>>,
    pub remove_channel_id: Option<String>,
    pub rename_channel_id: Option<String>,
    pub test_channel_id: Option<String>,
    pub email_recipient_mode: Option<String>,
    pub custom_email: Option<String>,
    pub selection_only: bool,
    pub clear_binding: bool,
    pub test_email: bool,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct TeamsWorkflowTestResult {
    pub request_id: String,
    pub saved: bool,
    pub binding_version: String,
    pub saved_at: String,
    pub accepted: bool,
    pub provider_status: i64,
    pub workflow_run_id: Option<String>,
    pub tested_at: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct SlackWebhookTestCommand {
    pub actor_id: String,
    pub request_id: String,
    pub webhook_url: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct SlackWebhookTestResult {
    pub request_id: String,
    pub accepted: bool,
    pub provider_status: i64,
    pub tested_at: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct BreakGlassActivationCommand {
    pub actor_oid: String,
    pub incident_id: String,
    pub reason: String,
    pub activated_at: String,
    pub expires_at: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct BreakGlassActivationRecord {
    pub activation_id: String,
    pub actor_oid: String,
    pub incident_id: String,
    pub activated_at: String,
    pub expires_at: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ConfigurationReviewCommand {
    pub principal_id: String,
    pub run_id: String,
    pub requested_at: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct HilPendingItem {
    pub approval_id: String,
    pub idempotency_key: String,
    pub submitter_oid: String,
    pub metadata: BTreeMap<String, String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct HilDecisionReceipt {
    pub approval_id: String,
    pub idempotency_key: String,
    pub decision: HilApprovalDecision,
    pub approver_oid: String,
    pub decided_at: String,
    pub receipt_ref: String,
    pub justification: String,
    pub already_recorded: bool,
    pub delivered: bool,
    #[allow(clippy::type_complexity)]
    pub development_attestation: Option<BTreeMap<String, String>>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct HilDecisionCommand {
    pub approval_id: String,
    pub idempotency_key: String,
    pub action_hash: String,
    pub decision: HilApprovalDecision,
    pub approver_oid: String,
    pub approver_roles: Vec<String>,
    pub justification: String,
    pub decided_at: String,
    pub expected_expires_at: String,
    pub expected_submitter_oid: String,
    pub expected_decision_route: String,
    pub expected_required_role: String,
    #[allow(clippy::type_complexity)]
    pub development_attestation: Option<BTreeMap<String, String>>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct HilDecisionOutboxRequest {
    pub receipt: Box<HilDecisionReceipt>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ReportLineContactContext {
    pub approval_id: String,
    pub requester_ref: String,
    pub consent_id: String,
    pub consent_revision: i64,
    pub action_type: String,
    pub target_ref: String,
    pub route_subjects: Vec<String>,
    pub consent_requested_at: String,
    pub expires_at: String,
}

impl AccessGrantRecord {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn to_dict(&self) -> String {
        core::hint::black_box(String::new())
    }
}

pub trait AccessGrantOutbox {
    fn snapshot(&self, query: AccessGrantSnapshotQuery) -> String;
}

impl DirectoryIdentity {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn to_dict(&self) -> String {
        core::hint::black_box(String::new())
    }
}

impl DirectoryStatus {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn to_dict(&self) -> String {
        core::hint::black_box(String::new())
    }
}

pub trait HumanIdentityDirectory {
    fn search(&self, query: String, limit: i64) -> String;
}

pub trait HumanIdentityDirectoryStatus {
    fn directory_status(&self) -> String;
}

pub trait StewardshipHealthReader {
    fn read_state(&self, key: String) -> String;
}

pub trait StewardshipIdentityDirectory {
    fn get_steward_subject_by_id(&self, subject_id: String, kind: String) -> String;
}

pub trait HumanAccessRequestOutbox {
    fn list_request_page(&self, query: AccessRequestQuery) -> String;
}

pub trait AssignmentRequestOutbox {
    fn list_case_page(&self, query: AssignmentCaseQuery) -> String;
}

pub trait ReportingLineOutbox {
    fn list_report_line_case_page(&self, query: ReportingLineCaseQuery) -> String;
}

pub trait HandoverGoalOutbox {
    fn invitation_for_session(&self, subject_ref: String, roles: std::collections::BTreeSet<String>, session_id: String) -> String;
}

pub trait HandoverReviewReader {
    fn may_review_goal(&self, goal: String, principal: IamPrincipal) -> String;
}

pub trait HandoverReadinessReader {
    fn lifecycle_readiness(&self) -> String;
}

pub trait ModelCatalogReader {
    fn read(&self, refresh: bool) -> String;
}

pub trait ModelSettingsOutbox {
    fn projection(&self, principal_id: String, can_manage_web_search: bool, can_manage_model_bindings: bool, refresh_model_catalog: bool, include_model_catalog: bool) -> String;
}

pub trait RuntimeSettingsOutbox {
    fn projection(&self, can_manage: bool) -> String;
}

pub trait TeamsWorkflowTester {
    fn save_and_test(&self, command: TeamsWorkflowTestCommand) -> String;
}

pub trait SlackWebhookTester {
    fn test(&self, command: SlackWebhookTestCommand) -> String;
}

impl BreakGlassActivationRecord {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn to_dict(&self) -> String {
        core::hint::black_box(String::new())
    }
}

pub trait BreakGlassActivationOutbox {
    fn activate(&self, command: BreakGlassActivationCommand) -> String;
}

pub trait ConfigurationReviewOutbox {
    fn run(&self, command: ConfigurationReviewCommand) -> String;
}

pub trait HilDecisionRegistry {
    fn get_pending_by_approval_id(&self, approval_id: String) -> String;
}

pub trait HilDecisionOutbox {
    fn enqueue(&self, request: HilDecisionOutboxRequest) -> String;
}

pub trait ReportLineContactOutbox {
    fn get_report_line_contact_context(&self, approval_id: String) -> String;
}

