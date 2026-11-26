#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum DiscoveryResultKind {
    #[default]
    List,
    Count,
    Types,
    Relationships,
    Coverage,
}

impl DiscoveryResultKind {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::List => "list",
            Self::Count => "count",
            Self::Types => "types",
            Self::Relationships => "relationships",
            Self::Coverage => "coverage",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum DiscoveryUniverse {
    #[default]
    ResourceContainers,
    ArmResources,
    ArmChildResources,
    ArgSpecialized,
    ResourceDetails,
    TenantDirectory,
    ServiceDataPlane,
}

impl DiscoveryUniverse {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::ResourceContainers => "resource_containers",
            Self::ArmResources => "arm_resources",
            Self::ArmChildResources => "arm_child_resources",
            Self::ArgSpecialized => "arg_specialized",
            Self::ResourceDetails => "resource_details",
            Self::TenantDirectory => "tenant_directory",
            Self::ServiceDataPlane => "service_data_plane",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum DiscoveryScopeKind {
    #[default]
    Tenant,
    ManagementGroup,
    Subscription,
    ResourceGroup,
    Resource,
    DataPlane,
}

impl DiscoveryScopeKind {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Tenant => "tenant",
            Self::ManagementGroup => "management_group",
            Self::Subscription => "subscription",
            Self::ResourceGroup => "resource_group",
            Self::Resource => "resource",
            Self::DataPlane => "data_plane",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum DiscoveryPredicateField {
    #[default]
    Name,
    ProviderType,
    SemanticType,
    ResourceGroup,
    Location,
    Tag,
    Status,
    Link,
}

impl DiscoveryPredicateField {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Name => "name",
            Self::ProviderType => "provider_type",
            Self::SemanticType => "semantic_type",
            Self::ResourceGroup => "resource_group",
            Self::Location => "location",
            Self::Tag => "tag",
            Self::Status => "status",
            Self::Link => "link",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum DiscoveryPredicateOperator {
    #[default]
    Eq,
    Contains,
    In,
    Exists,
}

impl DiscoveryPredicateOperator {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Eq => "eq",
            Self::Contains => "contains",
            Self::In => "in",
            Self::Exists => "exists",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum DiscoveryBackend {
    #[default]
    PromotedInventory,
    ResourceGraph,
    GenericArm,
    TypedArm,
    RegisteredCli,
    TypedDataPlane,
}

impl DiscoveryBackend {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::PromotedInventory => "promoted_inventory",
            Self::ResourceGraph => "resource_graph",
            Self::GenericArm => "generic_arm",
            Self::TypedArm => "typed_arm",
            Self::RegisteredCli => "registered_cli",
            Self::TypedDataPlane => "typed_data_plane",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum DiscoveryMappingStatus {
    #[default]
    Mapped,
    Unmapped,
}

impl DiscoveryMappingStatus {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Mapped => "mapped",
            Self::Unmapped => "unmapped",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum DiscoveryCoverageStatus {
    #[default]
    Covered,
    Fallback,
    Partial,
    Unsupported,
    Unavailable,
    Unauthorized,
    Unmapped,
}

impl DiscoveryCoverageStatus {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Covered => "covered",
            Self::Fallback => "fallback",
            Self::Partial => "partial",
            Self::Unsupported => "unsupported",
            Self::Unavailable => "unavailable",
            Self::Unauthorized => "unauthorized",
            Self::Unmapped => "unmapped",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct DiscoveryPredicate {
    pub field: DiscoveryPredicateField,
    pub operator: DiscoveryPredicateOperator,
    pub values: Vec<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct DiscoveryLimits {
    pub max_results: i64,
    pub max_pages: i64,
    pub max_bytes: i64,
    pub timeout_ms: i64,
    pub max_fan_out: i64,
    pub freshness_seconds: i64,
}

impl DiscoveryLimits {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !(1_i64..=10000_i64).contains(&self.max_results) { return Err("max_results out of bounds"); }
        if !(1_i64..=100_i64).contains(&self.max_pages) { return Err("max_pages out of bounds"); }
        if !(1024_i64..=67108864_i64).contains(&self.max_bytes) { return Err("max_bytes out of bounds"); }
        if !(100_i64..=120000_i64).contains(&self.timeout_ms) { return Err("timeout_ms out of bounds"); }
        if !(1_i64..=16_i64).contains(&self.max_fan_out) { return Err("max_fan_out out of bounds"); }
        if !(0_i64..=31536000_i64).contains(&self.freshness_seconds) { return Err("freshness_seconds out of bounds"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct DiscoveryIntent {
    pub schema_version: String,
    pub result_kind: DiscoveryResultKind,
    pub universes: Vec<DiscoveryUniverse>,
    pub scope_kind: DiscoveryScopeKind,
    pub scope_digest: String,
    pub predicates: Vec<DiscoveryPredicate>,
    pub limits: Box<DiscoveryLimits>,
    pub include_command_explanation: bool,
    pub unresolved_modifiers: Vec<String>,
    pub execution_authority: bool,
    pub intent_digest: String,
}

impl DiscoveryIntent {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.schema_version.as_str(), "1.0.0") { return Err("invalid schema_version literal"); }
        if self.execution_authority { return Err("execution_authority violated literal bool invariant"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct DiscoveryFallback {
    pub backend: DiscoveryBackend,
    pub reason_code: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct DiscoveryOperationProfile {
    pub operation_id: String,
    pub backend: DiscoveryBackend,
    pub universes: Vec<DiscoveryUniverse>,
    pub result_kinds: Vec<DiscoveryResultKind>,
    pub scope_kinds: Vec<DiscoveryScopeKind>,
    pub predicate_fields: Vec<DiscoveryPredicateField>,
    pub predicate_operators: Vec<DiscoveryPredicateOperator>,
    pub projection: Vec<String>,
    pub output_schema_id: String,
    pub normalization_id: String,
    pub validation_versions: Vec<String>,
    pub equivalence_key: String,
    pub identity_profile: String,
    pub priority: i64,
    pub command_template_id: Option<String>,
}

impl DiscoveryOperationProfile {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !(1_i64..=100_i64).contains(&self.priority) { return Err("priority out of bounds"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct DiscoveryProfile {
    pub schema_version: String,
    pub profile_id: String,
    pub revision: String,
    pub cloud: String,
    pub provider_type: String,
    pub semantic_type: Option<String>,
    pub operations: Vec<DiscoveryOperationProfile>,
    pub limits: Box<DiscoveryLimits>,
    pub provenance_refs: Vec<String>,
    pub profile_digest: String,
}

impl DiscoveryProfile {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.schema_version.as_str(), "1.1.0") { return Err("invalid schema_version literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct DiscoveryQueryPlan {
    pub schema_version: String,
    pub plan_id: String,
    pub intent_digest: String,
    pub result_kind: DiscoveryResultKind,
    pub profile_id: String,
    pub profile_revision: String,
    pub universes: Vec<DiscoveryUniverse>,
    pub backend: DiscoveryBackend,
    pub operation_id: String,
    pub equivalence_key: String,
    pub scope_kind: DiscoveryScopeKind,
    pub scope_digest: String,
    pub authorization_ceiling_digest: String,
    pub predicates: Vec<DiscoveryPredicate>,
    pub projection: Vec<String>,
    pub limits: Box<DiscoveryLimits>,
    pub fallback_history: Vec<DiscoveryFallback>,
    pub output_schema_id: String,
    pub normalization_id: String,
    pub validation_versions: Vec<String>,
    pub execution_authority: bool,
    pub plan_digest: String,
}

impl DiscoveryQueryPlan {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.schema_version.as_str(), "1.2.0") { return Err("invalid schema_version literal"); }
        if self.execution_authority { return Err("execution_authority violated literal bool invariant"); }
        Ok(())
    }
}

pub const DIGEST_PATTERN: &str = "^sha256:[a-f0-9]{64}$";
pub const ID_PATTERN: &str = "^[a-z][a-z0-9_.-]{0,127}$";
pub const PROVIDER_TYPE_PATTERN: &str = "^[A-Za-z][A-Za-z0-9.]{0,127}/[A-Za-z0-9._/-]{1,255}$";
pub const VERSION_REF_PATTERN: &str = "^[a-z][a-z0-9_.-]{0,63}@[A-Za-z0-9][A-Za-z0-9._-]{0,63}$";
pub const EXECUTABLE_CONTROL: &str = "[\\x00-\\x1f\\x7f`$;&|<>]|\\$\\(|\\b(?:eval|exec|source)\\b";
impl DiscoveryPredicate {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn values_are_bounded_data(&self) -> Result<DiscoveryPredicate, &'static str> {
        if (((self.values.clone()).len() as i64)) != ((((self.values.clone()).into_iter().collect::<std::collections::BTreeSet<String>>()).len() as i64)) {
            return Err("predicate values MUST be unique");
        }
        Ok(self.clone())
    }
}

impl DiscoveryIntent {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn intent_is_canonical(&self) -> Result<DiscoveryIntent, &'static str> {
        if !(self.unresolved_modifiers.clone()).is_empty() {
            return Err("discovery intent MUST NOT contain unresolved modifiers");
        }
        Ok(self.clone())
    }
}

impl DiscoveryOperationProfile {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn operation_is_canonical(&self) -> Result<DiscoveryOperationProfile, &'static str> {
        Err("runtime_binding_required")
    }
}

impl DiscoveryProfile {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn profile_is_canonical(&self) -> Result<DiscoveryProfile, &'static str> {
        if (((self.provenance_refs.clone()).len() as i64)) != ((((self.provenance_refs.clone()).into_iter().collect::<std::collections::BTreeSet<String>>()).len() as i64)) {
            return Err("discovery profile provenance refs MUST be unique");
        }
        Ok(self.clone())
    }
}

impl DiscoveryQueryPlan {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn plan_is_canonical(&self) -> Result<DiscoveryQueryPlan, &'static str> {
        if (((self.projection.clone()).len() as i64)) != ((((self.projection.clone()).into_iter().collect::<std::collections::BTreeSet<String>>()).len() as i64)) {
            return Err("discovery projection fields MUST be unique");
        }
        if (((self.validation_versions.clone()).len() as i64)) != ((((self.validation_versions.clone()).into_iter().collect::<std::collections::BTreeSet<String>>()).len() as i64)) {
            return Err("discovery validation versions MUST be unique");
        }
        Ok(self.clone())
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn discovery_intent_digest(mut values: std::collections::BTreeMap<String, String>) -> String {
    if values.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn discovery_plan_digest(mut values: std::collections::BTreeMap<String, String>) -> String {
    if values.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn discovery_profile_digest(mut values: std::collections::BTreeMap<String, String>) -> String {
    if values.is_empty() {
        return String::new();
    }
    String::new()
}

pub const PUBLIC_EXPORTS: &[&str] = &["DiscoveryBackend", "DiscoveryCoverageStatus", "DiscoveryFallback", "DiscoveryIntent", "DiscoveryLimits", "DiscoveryMappingStatus", "DiscoveryOperationProfile", "DiscoveryPredicate", "DiscoveryPredicateField", "DiscoveryPredicateOperator", "DiscoveryProfile", "DiscoveryQueryPlan", "DiscoveryResultKind", "DiscoveryScopeKind", "DiscoveryUniverse", "discovery_intent_digest", "discovery_plan_digest", "discovery_profile_digest"];
