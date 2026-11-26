use std::collections::BTreeMap;
pub const MAX_PROVIDER_TYPES: i64 = 10000;
pub const MAX_PROVIDER_TYPE_LENGTH: i64 = 512;

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum RelationshipDropReason {
    #[default]
    AmbiguousOrientation,
    ConflictingDuplicate,
    DuplicateEdge,
    MissingIndependentVerifier,
    MissingSourceEndpoint,
    MissingTargetEndpoint,
    PartialGeneration,
    StaleSourceSchemaDigest,
    TargetTypeMismatch,
    UnresolvedReference,
    UnverifiedMetadata,
}

impl RelationshipDropReason {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::AmbiguousOrientation => "ambiguous_orientation",
            Self::ConflictingDuplicate => "conflicting_duplicate",
            Self::DuplicateEdge => "duplicate_edge",
            Self::MissingIndependentVerifier => "missing_independent_verifier",
            Self::MissingSourceEndpoint => "missing_source_endpoint",
            Self::MissingTargetEndpoint => "missing_target_endpoint",
            Self::PartialGeneration => "partial_generation",
            Self::StaleSourceSchemaDigest => "stale_source_schema_digest",
            Self::TargetTypeMismatch => "target_type_mismatch",
            Self::UnresolvedReference => "unresolved_reference",
            Self::UnverifiedMetadata => "unverified_metadata",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum RelationshipUnavailableReason {
    #[default]
    AuthorizationChildScopeUnmodeled,
    ReferenceNotObserved,
    SourceOutsideActiveGeneration,
    TargetOutsideActiveGeneration,
    TargetProviderTypeUnmodeled,
}

impl RelationshipUnavailableReason {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::AuthorizationChildScopeUnmodeled => "authorization_child_scope_unmodeled",
            Self::ReferenceNotObserved => "reference_not_observed",
            Self::SourceOutsideActiveGeneration => "source_outside_active_generation",
            Self::TargetOutsideActiveGeneration => "target_outside_active_generation",
            Self::TargetProviderTypeUnmodeled => "target_provider_type_unmodeled",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct RelationshipDrop {
    pub reason: RelationshipDropReason,
    pub mapping_id: Option<String>,
    pub source_property_path: Option<String>,
    pub source_provider_type: Option<String>,
    pub target_provider_type: Option<String>,
    pub unavailable_reason: Option<RelationshipUnavailableReason>,
}

impl RelationshipDrop {
    pub fn validate(&self) -> Result<(), &'static str> {
        Err("runtime_binding_required")
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ProviderRelationshipEvidence {
    pub mapping_id: String,
    pub mapping_revision: String,
    pub mapping_receipt_ref: String,
    pub provider_identity: String,
    pub source_identity: String,
    pub source_property_path: String,
    pub source_schema_version: String,
    pub source_schema_digest: String,
    pub observed_schema_digest: String,
    pub evidence_method: String,
    pub freshness_ceiling_seconds: i64,
    pub endpoint_orientation: String,
    pub provider_owner_id: String,
    pub observation_receipt_ref: String,
    pub source_provider_type: Option<String>,
    pub target_provider_type: Option<String>,
}

impl ProviderRelationshipEvidence {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.mapping_id.trim().is_empty() { return Err("mapping_id must be non-empty"); }
        if self.mapping_revision.trim().is_empty() { return Err("mapping_revision must be non-empty"); }
        if self.mapping_receipt_ref.trim().is_empty() { return Err("mapping_receipt_ref must be non-empty"); }
        if self.provider_identity.trim().is_empty() { return Err("provider_identity must be non-empty"); }
        if self.source_identity.trim().is_empty() { return Err("source_identity must be non-empty"); }
        if self.source_property_path.trim().is_empty() { return Err("source_property_path must be non-empty"); }
        if self.source_schema_version.trim().is_empty() { return Err("source_schema_version must be non-empty"); }
        if self.source_schema_digest.trim().is_empty() { return Err("source_schema_digest must be non-empty"); }
        if self.observed_schema_digest.trim().is_empty() { return Err("observed_schema_digest must be non-empty"); }
        if self.evidence_method.trim().is_empty() { return Err("evidence_method must be non-empty"); }
        if self.endpoint_orientation.trim().is_empty() { return Err("endpoint_orientation must be non-empty"); }
        if self.provider_owner_id.trim().is_empty() { return Err("provider_owner_id must be non-empty"); }
        if self.observation_receipt_ref.trim().is_empty() { return Err("observation_receipt_ref must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ProviderTypeCount {
    pub provider_type: String,
    pub count: i64,
}

impl ProviderTypeCount {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.provider_type.trim().is_empty() { return Err("provider_type must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ProviderScopeCoverage {
    pub capture_method: String,
    pub provider_object_count: i64,
    pub mapped_provider_object_count: i64,
    pub provider_type_count: i64,
    pub unmapped_provider_types: Vec<ProviderTypeCount>,
    pub materialized_unmapped_provider_object_count: i64,
    #[allow(clippy::type_complexity)]
    pub mapped_provider_types: Option<Vec<ProviderTypeCount>>,
}

impl ProviderScopeCoverage {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.capture_method.trim().is_empty() { return Err("capture_method must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ResourceRecord {
    pub resource_id: String,
    pub r#type: String,
    pub props: BTreeMap<String, String>,
    pub provider_ref: Option<String>,
    pub last_seen: Option<String>,
}

impl ResourceRecord {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.resource_id.trim().is_empty() { return Err("resource_id must be non-empty"); }
        if self.r#type.trim().is_empty() { return Err("type must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct LinkRecord {
    pub from_id: String,
    pub from_type: String,
    pub link_type: String,
    pub to_id: String,
    pub to_type: String,
    pub link_props: BTreeMap<String, String>,
    #[allow(clippy::type_complexity)]
    pub mapping_evidence: Option<Box<ProviderRelationshipEvidence>>,
    pub observation_metadata: Option<String>,
}

impl LinkRecord {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.from_id.trim().is_empty() { return Err("from_id must be non-empty"); }
        if self.from_type.trim().is_empty() { return Err("from_type must be non-empty"); }
        if self.link_type.trim().is_empty() { return Err("link_type must be non-empty"); }
        if self.to_id.trim().is_empty() { return Err("to_id must be non-empty"); }
        if self.to_type.trim().is_empty() { return Err("to_type must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct InventoryBatch {
    pub resources: Vec<ResourceRecord>,
    pub links: Vec<LinkRecord>,
    pub relationship_drops: Vec<RelationshipDrop>,
    pub cursor: Option<String>,
    pub r#final: bool,
    pub relationship_reconciliation_after: Option<String>,
    #[allow(clippy::type_complexity)]
    pub provider_scope_coverage: Option<Box<ProviderScopeCoverage>>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct PromotedInventoryGeneration {
    pub generation: String,
    pub resources: Vec<ResourceRecord>,
    pub complete: bool,
    pub recorded_at: Option<String>,
}

pub const INVENTORY_RELATIONSHIP_RECONCILIATION_PREFIX: &str = "inventory-relationship-reconciliation:";
pub const UNCLASSIFIED_RESOURCE_TYPE: &str = "unclassified-resource";
impl RelationshipDrop {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn classified_unavailable(&self) -> bool {
        self.unavailable_reason.is_some()
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct InventoryGraphViewNotFoundError {
    pub message: String,
}

impl InventoryGraphViewNotFoundError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for InventoryGraphViewNotFoundError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for InventoryGraphViewNotFoundError {}

impl ProviderScopeCoverage {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn unmapped_provider_object_count(&self) -> i64 {
        (self.provider_object_count).saturating_sub(self.mapped_provider_object_count)
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn provider_identity_complete(&self) -> bool {
        core::hint::black_box(false)
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn to_metadata(&self) -> std::collections::BTreeMap<String, String> {
        std::collections::BTreeMap::from([(String::from("schema_version"), String::from("1.1.0")), (String::from("capture_method"), self.capture_method.clone()), (String::from("provider_object_count"), String::new()), (String::from("mapped_provider_object_count"), String::new()), (String::from("unmapped_provider_object_count"), String::new()), (String::from("materialized_unmapped_provider_object_count"), String::new()), (String::from("provider_identity_complete"), String::new()), (String::from("provider_type_count"), String::new()), (String::from("unmapped_provider_type_count"), String::new()), (String::from("unmapped_provider_types"), String::new())])
    }
}

pub trait Inventory {
    fn full_snapshot(&self, since: Option<String>) -> Vec<InventoryBatch>;
    fn delta(&self, cursor: String) -> Vec<InventoryBatch>;
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct EmptyInventory {
    pub initialized: bool,
}

impl EmptyInventory {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn full_snapshot(&self, mut since: Option<String>) -> Vec<InventoryBatch> {
        if !self.initialized {
            return Vec::new();
        }
        Vec::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn delta(&self, mut cursor: String) -> Vec<InventoryBatch> {
        if !self.initialized {
            return Vec::new();
        }
        Vec::new()
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct PromotedInventoryGenerationUnavailableError {
    pub message: String,
}

impl PromotedInventoryGenerationUnavailableError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for PromotedInventoryGenerationUnavailableError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for PromotedInventoryGenerationUnavailableError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct PromotedInventoryGenerationLimitError {
    pub message: String,
}

impl PromotedInventoryGenerationLimitError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for PromotedInventoryGenerationLimitError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for PromotedInventoryGenerationLimitError {}

pub trait PromotedInventoryGenerationReader {
    fn active_generation_id(&self) -> Option<String>;
    fn load_active_generation(&self, max_resources: i64) -> Option<PromotedInventoryGeneration>;
}

pub const PUBLIC_EXPORTS: &[&str] = &["EmptyInventory", "Inventory", "InventoryBatch", "InventoryGraphViewNotFoundError", "LinkRecord", "PromotedInventoryGeneration", "PromotedInventoryGenerationLimitError", "PromotedInventoryGenerationReader", "PromotedInventoryGenerationUnavailableError", "ProviderRelationshipEvidence", "ProviderScopeCoverage", "ProviderTypeCount", "RelationshipDrop", "RelationshipDropReason", "ResourceRecord", "UNCLASSIFIED_RESOURCE_TYPE"];
