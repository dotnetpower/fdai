pub const MAX_RESOLVED_MODELS_BYTES: i64 = 1000000;

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum CapabilityStatus {
    #[default]
    Resolved,
    HilOnly,
    CapacityReduced,
}

impl CapabilityStatus {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Resolved => "resolved",
            Self::HilOnly => "hil-only",
            Self::CapacityReduced => "capacity-reduced",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ResolvedCapability {
    pub name: String,
    pub status: CapabilityStatus,
    pub publisher: Option<String>,
    pub family: Option<String>,
    pub sku: Option<String>,
    pub capacity_tpm: i64,
    pub invocation: String,
    pub reasons: Vec<String>,
    pub capacity_unit: String,
    pub capacity_value: Option<i64>,
    pub selection_mode: String,
    pub version: Option<String>,
}

impl ResolvedCapability {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.name.trim().is_empty() { return Err("name must be non-empty"); }
        if self.invocation.trim().is_empty() { return Err("invocation must be non-empty"); }
        if self.capacity_unit.trim().is_empty() { return Err("capacity_unit must be non-empty"); }
        if self.selection_mode.trim().is_empty() { return Err("selection_mode must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct NarratorCandidate {
    pub endpoint: String,
    pub deployment: String,
    pub api_version: String,
    pub api_style: String,
    pub auth_audience: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ResolvedModels {
    pub schema_version: String,
    pub region: String,
    pub subscription_id: String,
    pub deployer_object_id: String,
    pub mixed_model_mode: String,
    pub capabilities: Vec<ResolvedCapability>,
    #[allow(clippy::type_complexity)]
    pub narrator: Option<Box<NarratorCandidate>>,
    pub narrator_candidates: Vec<NarratorCandidate>,
    pub vision_candidates: Vec<NarratorCandidate>,
    pub web_search_candidates: Vec<NarratorCandidate>,
    pub reasoner_primary_candidates: Vec<NarratorCandidate>,
    pub endpoint_bindings: Vec<String>,
    pub binding_policy_environment: Option<String>,
    pub binding_policy_revision: Option<i64>,
    pub binding_policy_digest: Option<String>,
    pub binding_policy_expected_active_digest: Option<String>,
}

impl ResolvedModels {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.schema_version.trim().is_empty() { return Err("schema_version must be non-empty"); }
        if self.region.trim().is_empty() { return Err("region must be non-empty"); }
        if self.subscription_id.trim().is_empty() { return Err("subscription_id must be non-empty"); }
        if self.deployer_object_id.trim().is_empty() { return Err("deployer_object_id must be non-empty"); }
        if self.mixed_model_mode.trim().is_empty() { return Err("mixed_model_mode must be non-empty"); }
        Ok(())
    }
}

pub const MIN_QUOTA_RATIO: f64 = 0.2;
pub const RESOLVED_MODELS_SCHEMA_VERSION: &str = "1.0.0";
pub const SHA256_DIGEST: &str = "^sha256:[0-9a-f]{64}$";
pub const VIRTUAL_CAPABILITIES: &[&str] = &["t1.vision"];
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ResolverError {
    pub message: String,
}

impl ResolverError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for ResolverError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for ResolverError {}

pub trait CatalogQuery {
    fn families_in_region(&self, region: String) -> String;
}

pub trait PublisherCatalogQuery {
    fn publisher_families_in_region(&self, region: String) -> String;
}

pub trait ModelVersionQuery {
    fn latest_stable_version(&self, region: String, publisher: String, family: String) -> String;
}

pub trait PermissionQuery {
    fn principal_has_cognitive_services_contributor(&self, subscription_id: String, principal_object_id: String) -> String;
}

pub trait QuotaQuery {
    fn available_capacity_tpm(&self, region: String, publisher: String, family: String) -> String;
}

pub trait SkuQuotaQuery {
    fn available_capacity_tpm_for_sku(&self, region: String, publisher: String, family: String, sku: String) -> String;
}

pub trait ProvisionedCapacityQuery {
    fn available_capacity_ptu(&self, region: String, publisher: String, family: String, sku: String) -> String;
}

impl ResolvedModels {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn to_json(&self) -> String {
        let mut payload: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("schema_version"), self.schema_version.clone()), (String::from("region"), self.region.clone()), (String::from("subscription_id"), self.subscription_id.clone()), (String::from("deployer_object_id"), self.deployer_object_id.clone()), (String::from("mixed_model_mode"), self.mixed_model_mode.clone()), (String::from("capabilities"), String::new())]);
        String::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn from_json(mut text: String) -> ResolvedModels {
        if text.is_empty() {
            return Default::default();
        }
        Default::default()
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
#[allow(clippy::type_complexity)]
#[allow(clippy::too_many_arguments)]
pub fn resolve(mut registry: String, mut region: String, mut subscription_id: String, mut deployer_object_id: String, mut catalog: String, mut permission: String, mut quota: String, mut provisioned_capacity: Option<String>, mut tool_calling_families: Option<std::collections::BTreeSet<String>>, mut binding_policy: Option<String>, mut model_versions: Option<String>) -> ResolvedModels {
    let mut entries: Vec<ResolvedCapability> = Vec::<ResolvedCapability>::new();
    ResolvedModels { schema_version: String::from("1.0.0"), region: region.clone(), subscription_id: subscription_id.clone(), deployer_object_id: deployer_object_id.clone(), capabilities: entries.clone(), ..Default::default() }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn enforce_mixed_model_invariant(mut entries: Vec<ResolvedCapability>) {
    if entries.is_empty() {
        return;
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn enforce_distinct_family(mut left: Option<ResolvedCapability>, mut right: Option<ResolvedCapability>, mut pair: String) -> Result<(), &'static str> {
    if (left.is_none()) || (right.is_none()) {
        return Ok(());
    }
    Ok(())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn enforce_distinct_publisher(mut left: Option<ResolvedCapability>, mut right: Option<ResolvedCapability>, mut pair: String) -> Result<(), &'static str> {
    if (left.is_none()) || (right.is_none()) {
        return Ok(());
    }
    Ok(())
}

pub const PUBLIC_EXPORTS: &[&str] = &["CapabilityStatus", "CatalogQuery", "ModelVersionQuery", "NarratorCandidate", "PermissionQuery", "PublisherCatalogQuery", "QuotaQuery", "ResolvedCapability", "ResolvedModels", "ResolverError", "SkuQuotaQuery", "collect_narrator", "collect_narrator_deployments", "collect_vision_candidates", "collect_primary_candidates", "collect_primary_deployments", "collect_web_search_candidates", "collect_web_search_deployments", "narrator_deployment_name", "reasoner_primary_deployment_name", "web_search_deployment_name", "resolve"];
