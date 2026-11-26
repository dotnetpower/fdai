use std::collections::BTreeMap;
#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum MixedModelMode {
    #[default]
    AzureFoundry,
    External,
    HilOnly,
}

impl MixedModelMode {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::AzureFoundry => "azure-foundry",
            Self::External => "external",
            Self::HilOnly => "hil-only",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum Sku {
    #[default]
    Standard,
    GlobalStandard,
    ProvisionedManaged,
    GlobalProvisionedManaged,
    DataZoneProvisionedManaged,
}

impl Sku {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Standard => "Standard",
            Self::GlobalStandard => "GlobalStandard",
            Self::ProvisionedManaged => "ProvisionedManaged",
            Self::GlobalProvisionedManaged => "GlobalProvisionedManaged",
            Self::DataZoneProvisionedManaged => "DataZoneProvisionedManaged",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum Invocation {
    #[default]
    Always,
    OnDisagreement,
    OnNovelCase,
}

impl Invocation {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Always => "always",
            Self::OnDisagreement => "on_disagreement",
            Self::OnNovelCase => "on_novel_case",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct LlmRegistryIssue {
    pub key: String,
    pub message: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct FamilyPreference {
    pub publisher: String,
    pub family: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CapabilitySpec {
    pub preferences: Vec<FamilyPreference>,
    pub sku: Sku,
    pub capacity_tpm: Option<i64>,
    pub capacity_ptu: Option<i64>,
    pub invocation: Invocation,
    pub tool_calling_required: bool,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct LlmRegistry {
    pub schema_version: String,
    pub mixed_model_mode: MixedModelMode,
    pub models: BTreeMap<String, CapabilitySpec>,
}

pub const SCHEMA_PACKAGE: &str = "fdai.rule_catalog.schema";
pub const SCHEMA_FILE: &str = "llm_registry.schema.json";
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct LlmRegistryError {
    pub message: String,
}

impl LlmRegistryError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for LlmRegistryError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for LlmRegistryError {}

impl CapabilitySpec {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn require_capacity_for_sku(&self) -> Result<CapabilitySpec, &'static str> {
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn capacity_unit(&self) -> String {
        String::from("ptu\" if self.sku.is_provisioned else \"tpm")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn requested_capacity(&self) -> Result<i64, &'static str> {
        Ok(0_i64)
    }
}

impl LlmRegistry {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn require_mixed_model_family_distinct(&self) -> Result<LlmRegistry, &'static str> {
        Err("runtime_binding_required")
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn load_json_schema() -> std::collections::BTreeMap<String, String> {
    std::collections::BTreeMap::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn load_llm_registry_from_mapping(mut raw: std::collections::BTreeMap<String, String>) -> Result<LlmRegistry, &'static str> {
    let mut issues: Vec<LlmRegistryIssue> = Vec::<LlmRegistryIssue>::new();
    let schema: std::collections::BTreeMap<String, String> = load_json_schema();
    if !(issues.clone()).is_empty() {
        return Err("issues");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn load_llm_registry_from_yaml(mut path: String) -> Result<LlmRegistry, &'static str> {
    Ok(load_llm_registry_from_mapping(std::collections::BTreeMap::new()).unwrap_or_else(|_| Default::default()))
}

pub const PUBLIC_EXPORTS: &[&str] = &["CapabilitySpec", "FamilyPreference", "Invocation", "LlmRegistry", "LlmRegistryError", "LlmRegistryIssue", "MixedModelMode", "Sku", "load_llm_registry_from_mapping", "load_llm_registry_from_yaml"];
