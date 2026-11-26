#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum EndpointOrientation {
    #[default]
    OwnerToReferenced,
    ReferencedToOwner,
}

impl EndpointOrientation {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::OwnerToReferenced => "owner_to_referenced",
            Self::ReferencedToOwner => "referenced_to_owner",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ProviderReferenceFormat {
    #[default]
    ArmId,
    ExactIdentity,
    LabelSelector,
    ProviderIdentity,
    ResolvedName,
    ResolvedNames,
    ResolvedUid,
}

impl ProviderReferenceFormat {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::ArmId => "arm_id",
            Self::ExactIdentity => "exact_identity",
            Self::LabelSelector => "label_selector",
            Self::ProviderIdentity => "provider_identity",
            Self::ResolvedName => "resolved_name",
            Self::ResolvedNames => "resolved_names",
            Self::ResolvedUid => "resolved_uid",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct SourceSchemaIdentity {
    pub version: String,
    pub digest: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct RelationshipFreshnessPolicy {
    pub max_age_seconds: i64,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct RelationshipCompletenessPolicy {
    pub require_complete_generation: bool,
    pub require_source_endpoint: bool,
    pub require_target_endpoint: bool,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct RelationshipPredicate {
    pub property_path: String,
    pub equals: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ProviderRelationshipMapping {
    pub mapping_id: String,
    pub provider: String,
    pub source_identity: String,
    pub source_provider_types: Vec<String>,
    pub source_property_path: String,
    pub target_provider_types: Vec<String>,
    pub reference_format: ProviderReferenceFormat,
    #[allow(clippy::type_complexity)]
    pub predicate: Option<Box<RelationshipPredicate>>,
    pub link_type: String,
    pub endpoint_orientation: EndpointOrientation,
    pub cardinality: Option<String>,
    pub source_schema: Box<SourceSchemaIdentity>,
    pub evidence_method: String,
    pub freshness: Box<RelationshipFreshnessPolicy>,
    pub completeness: Box<RelationshipCompletenessPolicy>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct RelationshipMappingReview {
    pub reviewer_identity: String,
    pub reviewed_at: String,
    pub immutable_receipt_ref: String,
    pub content_hash: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ProviderRelationshipMappingCatalog {
    pub schema_version: String,
    pub mappings: Vec<ProviderRelationshipMapping>,
    pub review: Box<RelationshipMappingReview>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ProviderRelationshipMappingIssue {
    pub key: String,
    pub message: String,
}

pub const SHA256_PREFIX: &str = "sha256:";
pub const CARDINALITIES: &[&str] = &["one_to_one", "one_to_many", "many_to_one", "many_to_many"];
impl SourceSchemaIdentity {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn validate_digest(mut value: String) -> String {
        let _ = require_sha256(value.clone(), String::from("source schema digest")).unwrap_or_else(|_| ());
        value.clone()
    }
}

impl RelationshipCompletenessPolicy {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn require_closed_generation(&self) -> Result<RelationshipCompletenessPolicy, &'static str> {
        Err("runtime_binding_required")
    }
}

impl ProviderRelationshipMapping {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub fn canonical_provider_types(mut values: Vec<String>) -> Result<Vec<String>, &'static str> {
        if values.is_empty() {
            return Err("missing_required_input");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn trusted_evidence_method(mut value: String) -> Result<String, &'static str> {
        Ok(value.clone())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn bounded_cardinality(mut value: String) -> Result<String, &'static str> {
        Ok(value.clone())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn default_cardinality(&self) -> ProviderRelationshipMapping {
        core::hint::black_box(Default::default())
    }
}

impl RelationshipMappingReview {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn timezone_aware(mut value: String) -> Result<String, &'static str> {
        Ok(value.clone())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn content_hash_shape(mut value: String) -> String {
        let _ = require_sha256(value.clone(), String::from("mapping catalog content hash")).unwrap_or_else(|_| ());
        value.clone()
    }
}

impl ProviderRelationshipMappingCatalog {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn reject_ambiguous_mappings(&self) -> Result<ProviderRelationshipMappingCatalog, &'static str> {
        let mut seen_ids: std::collections::BTreeSet<String> = std::collections::BTreeSet::<String>::new();
        let mut seen_routes: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::<String, String>::new();
        let mut parent_containment_owners: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::<String, String>::new();
        for mapping in self.mappings.clone() {
            if (seen_ids.clone()).contains((mapping.mapping_id.clone()).as_str()) {
                return Err("duplicate provider relationship mapping mapping.mapping_idr");
            }
            seen_ids.insert(mapping.mapping_id.clone());
        }
        Ok(self.clone())
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ProviderRelationshipMappingCatalogError {
    pub message: String,
}

impl ProviderRelationshipMappingCatalogError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for ProviderRelationshipMappingCatalogError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for ProviderRelationshipMappingCatalogError {}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn provider_relationship_mapping_content_hash(mut value: std::collections::BTreeMap<String, String>) -> String {
    if value.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn load_provider_relationship_mapping_catalog(mut root: String) -> Result<ProviderRelationshipMappingCatalog, &'static str> {
    let mut issues: Vec<ProviderRelationshipMappingIssue> = Vec::<ProviderRelationshipMappingIssue>::new();
    let expected_hash: String = provider_relationship_mapping_content_hash(std::collections::BTreeMap::new());
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn require_sha256(mut value: String, mut field_name: String) -> Result<(), &'static str> {
    if value.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

pub const PUBLIC_EXPORTS: &[&str] = &["EndpointOrientation", "ProviderReferenceFormat", "ProviderRelationshipMapping", "ProviderRelationshipMappingCatalog", "ProviderRelationshipMappingCatalogError", "ProviderRelationshipMappingIssue", "RelationshipCompletenessPolicy", "RelationshipFreshnessPolicy", "RelationshipMappingReview", "RelationshipPredicate", "SourceSchemaIdentity", "load_provider_relationship_mapping_catalog", "provider_relationship_mapping_content_hash"];
