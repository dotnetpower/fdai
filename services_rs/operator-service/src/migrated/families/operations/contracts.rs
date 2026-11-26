use std::collections::BTreeMap;
#[derive(Clone, Debug, Default, PartialEq)]
pub struct ProjectionQuery {
    pub operation: String,
    pub principal_id: String,
    pub path: BTreeMap<String, String>,
    #[allow(clippy::type_complexity)]
    pub params: BTreeMap<String, Vec<String>>,
    pub limit: i64,
    pub cursor: Option<String>,
    pub roles: Vec<String>,
    pub purpose: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct InventoryRelationshipDropClassification {
    pub reason: String,
    pub mapping_id: String,
    pub source_property_path: String,
    pub source_provider_type: String,
    pub target_provider_type: String,
    pub unavailable_reason: String,
    pub count: i64,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct InventoryProjectionSourceState {
    pub source: String,
    pub status: String,
    pub observed_at: Option<String>,
    pub reason: Option<String>,
    pub scope_digest: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct InventoryRelationshipCoverage {
    pub materialized: i64,
    pub reviewed_unavailable: i64,
    pub unclassified: i64,
    pub total_candidates: i64,
    pub complete: bool,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct InventoryProviderTypeCount {
    pub provider_type: String,
    pub count: i64,
}

impl InventoryProviderTypeCount {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.provider_type.trim().is_empty() { return Err("provider_type must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct InventoryProviderScopeCoverage {
    pub capture_method: String,
    pub provider_object_count: i64,
    pub mapped_provider_object_count: i64,
    pub unmapped_provider_object_count: i64,
    pub materialized_unmapped_provider_object_count: i64,
    pub provider_identity_complete: bool,
    pub provider_type_count: i64,
    pub unmapped_provider_types: Vec<InventoryProviderTypeCount>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct InventoryImpactContext {
    pub snapshot_id: String,
    pub observed_at: String,
    pub relationship_drop_reasons: Vec<String>,
    pub relationship_drop_classifications: Vec<InventoryRelationshipDropClassification>,
    pub projection_source_states: Vec<InventoryProjectionSourceState>,
    #[allow(clippy::type_complexity)]
    pub relationship_coverage: Option<Box<InventoryRelationshipCoverage>>,
    #[allow(clippy::type_complexity)]
    pub provider_scope_coverage: Option<Box<InventoryProviderScopeCoverage>>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct InventoryImpactEdge {
    pub source: String,
    pub target: String,
    pub link_type: String,
    #[allow(clippy::type_complexity)]
    pub evidence: Option<Box<InventoryRelationshipEvidence>>,
}

impl InventoryImpactEdge {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.source.trim().is_empty() { return Err("source must be non-empty"); }
        if self.target.trim().is_empty() { return Err("target must be non-empty"); }
        if self.link_type.trim().is_empty() { return Err("link_type must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct InventoryImpactLinkPage {
    pub edges: Vec<InventoryImpactEdge>,
    pub truncated: bool,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct InventoryInstanceResource {
    pub resource_id: String,
    pub resource_type: String,
    pub properties: BTreeMap<String, String>,
    pub last_seen: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct InventoryRelationshipEvidence {
    pub source_identity: String,
    pub source_property_path: String,
    pub mapping_id: String,
    pub evidence_method: String,
    pub freshness_ceiling_seconds: i64,
    pub evidence_kind: String,
    pub evidence_cutoff: Option<String>,
}

impl InventoryRelationshipEvidence {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.source_identity.trim().is_empty() { return Err("source_identity must be non-empty"); }
        if self.source_property_path.trim().is_empty() { return Err("source_property_path must be non-empty"); }
        if self.mapping_id.trim().is_empty() { return Err("mapping_id must be non-empty"); }
        if self.evidence_method.trim().is_empty() { return Err("evidence_method must be non-empty"); }
        if self.evidence_kind.trim().is_empty() { return Err("evidence_kind must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct InventoryInstanceEdge {
    pub source: String,
    pub target: String,
    pub link_type: String,
    #[allow(clippy::type_complexity)]
    pub evidence: Option<Box<InventoryRelationshipEvidence>>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct InventoryInstanceNeighborhood {
    pub resources: Vec<InventoryInstanceResource>,
    pub edges: Vec<InventoryInstanceEdge>,
    pub truncated: bool,
    pub truncation_reasons: Vec<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct InventoryInstanceResourcePage {
    pub resources: Vec<InventoryInstanceResource>,
    pub truncated: bool,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct InventoryInstanceActivity {
    pub sequence: i64,
    pub action_kind: String,
    pub actor: String,
    pub recorded_at: String,
    pub correlation_id: Option<String>,
    pub facts: BTreeMap<String, String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct InventoryInstanceActivityPage {
    pub activities: Vec<InventoryInstanceActivity>,
    pub truncated: bool,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct InventoryAksDiagnosticReceipt {
    pub principal_class: String,
    pub producer_version: String,
    pub method_version: String,
    pub target_resource_id: String,
    pub target_uid: String,
    pub target_resource_version: String,
    pub ontology_release: String,
    pub cutoff: String,
    pub source_cutoffs: BTreeMap<String, String>,
    pub source_revisions: BTreeMap<String, String>,
    pub status: String,
    pub signals: Vec<String>,
    pub complete: bool,
    pub evidence_gaps: Vec<String>,
    pub conflicts: Vec<String>,
    pub evidence_refs: Vec<String>,
    pub audit_correlation_id: String,
    pub cause_claim_supported: bool,
    pub execution_authority: bool,
}

impl InventoryAksDiagnosticReceipt {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.principal_class.trim().is_empty() { return Err("principal_class must be non-empty"); }
        if self.producer_version.trim().is_empty() { return Err("producer_version must be non-empty"); }
        if self.method_version.trim().is_empty() { return Err("method_version must be non-empty"); }
        if self.target_resource_id.trim().is_empty() { return Err("target_resource_id must be non-empty"); }
        if self.target_uid.trim().is_empty() { return Err("target_uid must be non-empty"); }
        if self.target_resource_version.trim().is_empty() { return Err("target_resource_version must be non-empty"); }
        if self.ontology_release.trim().is_empty() { return Err("ontology_release must be non-empty"); }
        if self.cutoff.trim().is_empty() { return Err("cutoff must be non-empty"); }
        if self.status.trim().is_empty() { return Err("status must be non-empty"); }
        if self.audit_correlation_id.trim().is_empty() { return Err("audit_correlation_id must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct EventProposal {
    pub operation: String,
    pub principal_id: Option<String>,
    pub idempotency_key: String,
    pub correlation_id: Option<String>,
    pub payload: BTreeMap<String, String>,
    pub principal_roles: Vec<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ProposalReceipt {
    pub request_id: String,
    pub correlation_id: Option<String>,
    pub dispatch_status: String,
    pub accepted_at: String,
    pub durably_queued: bool,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ReplayQuery {
    pub stream: String,
    pub principal_id: String,
    pub after_sequence: Option<i64>,
    pub limit: i64,
    pub cursor_epoch: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ReplayEvent {
    pub sequence: i64,
    pub event: String,
    pub data: BTreeMap<String, String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ReplayBatch {
    pub events: Vec<ReplayEvent>,
    pub watermark: i64,
}

pub const UNSELECTABLE_INSTANCE_DIRECTORY_TYPES: &[&str] = &["authorization.role-assignment"];
pub const REASON_CODE: &str = "^[a-z0-9][a-z0-9_.-]{0,127}$";
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ProjectionUnavailableError {
    pub message: String,
}

impl ProjectionUnavailableError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for ProjectionUnavailableError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for ProjectionUnavailableError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ProjectionNotFoundError {
    pub message: String,
}

impl ProjectionNotFoundError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for ProjectionNotFoundError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for ProjectionNotFoundError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ProposalConflictError {
    pub message: String,
}

impl ProposalConflictError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for ProposalConflictError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for ProposalConflictError {}

pub trait ProjectionReader {
    fn read(&self, query: ProjectionQuery) -> std::collections::BTreeMap<String, String>;
}

pub trait InventoryImpactReader {
    fn read_inventory_impact_context(&self) -> Option<InventoryImpactContext>;
    fn read_inventory_ontology_context(&self) -> Option<String>;
    fn inventory_resource_exists(&self, snapshot_id: String, resource_id: String) -> bool;
    fn inventory_resources_exist(&self, snapshot_id: String, resource_ids: Vec<String>) -> bool;
    fn read_inventory_outgoing_links(&self, snapshot_id: String, source_ids: Vec<String>, link_types: Vec<String>, limit: i64) -> InventoryImpactLinkPage;
}

pub trait InventoryInstanceReader {
    fn read_inventory_impact_context(&self) -> Option<InventoryImpactContext>;
    fn read_inventory_instance_neighborhood(&self, snapshot_id: String, root_id: String, link_types: Vec<String>, depth: i64, limit: i64) -> InventoryInstanceNeighborhood;
    fn read_inventory_instances(&self, snapshot_id: String, search: Option<String>, limit: i64) -> InventoryInstanceResourcePage;
    fn read_inventory_instance_activity(&self, resource_id: String, limit: i64) -> InventoryInstanceActivityPage;
    fn read_latest_aks_diagnostic_receipt(&self, resource_id: String) -> Option<InventoryAksDiagnosticReceipt>;
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ReportPdfEncodingError {
    pub message: String,
}

impl ReportPdfEncodingError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for ReportPdfEncodingError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for ReportPdfEncodingError {}

pub trait ReportPdfEncoder {
    fn name(&self) -> String;
    fn content_type(&self) -> String;
    fn encode(&self, report: std::collections::BTreeMap<String, String>) -> Vec<u8>;
}

impl ProposalReceipt {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn to_dict(&self) -> std::collections::BTreeMap<String, String> {
        std::collections::BTreeMap::from([(String::from("request_id"), self.request_id.clone()), (String::from("correlation_id"), (self.correlation_id.clone()).unwrap_or_default()), (String::from("dispatch_status"), self.dispatch_status.clone()), (String::from("accepted_at"), self.accepted_at.clone()), (String::from("durably_queued"), String::new())])
    }
}

pub trait EventProposalWriter {
    fn propose(&self, proposal: EventProposal) -> ProposalReceipt;
}

pub trait DurableReplayReader {
    fn replay(&self, query: ReplayQuery) -> ReplayBatch;
}

pub trait WebhookVerifier {
    fn verify(&self, operation: String, headers: std::collections::BTreeMap<String, String>, body: Vec<u8>) -> bool;
}

pub const PUBLIC_EXPORTS: &[&str] = &["DurableReplayReader", "EventProposal", "EventProposalWriter", "InventoryImpactContext", "InventoryImpactEdge", "InventoryImpactLinkPage", "InventoryImpactReader", "InventoryProviderScopeCoverage", "InventoryProviderTypeCount", "InventoryRelationshipCoverage", "InventoryRelationshipDropClassification", "ProjectionQuery", "ProjectionReader", "ProjectionNotFoundError", "ProjectionUnavailableError", "ReportPdfEncoder", "ReportPdfEncodingError", "ProposalConflictError", "ProposalReceipt", "ReplayBatch", "ReplayEvent", "ReplayQuery", "WebhookVerifier"];
