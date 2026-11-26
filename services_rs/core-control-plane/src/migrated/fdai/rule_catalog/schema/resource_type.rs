use std::collections::BTreeMap;
#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ResourceTypeCategory {
    #[default]
    Compute,
    Network,
    Storage,
    Database,
    Security,
    Observability,
    Governance,
}

impl ResourceTypeCategory {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Compute => "compute",
            Self::Network => "network",
            Self::Storage => "storage",
            Self::Database => "database",
            Self::Security => "security",
            Self::Observability => "observability",
            Self::Governance => "governance",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ResourceTypeEntry {
    pub id: String,
    pub category: ResourceTypeCategory,
    pub description: String,
    pub azure_arm_type: Option<String>,
    pub azure_kind_tokens: Vec<String>,
    pub query_terms: Vec<String>,
    pub typical_parents: Vec<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ResourceTypeQueryGroup {
    pub id: String,
    pub terms: Vec<String>,
    pub members: Vec<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ResourceTypeRegistry {
    pub schema_version: String,
    pub version: String,
    #[allow(clippy::type_complexity)]
    pub category_query_terms: BTreeMap<ResourceTypeCategory, Vec<String>>,
    pub query_groups: Vec<ResourceTypeQueryGroup>,
    pub types: Vec<ResourceTypeEntry>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ResourceTypeIssue {
    pub key: String,
    pub message: String,
}

pub const SCHEMA_PACKAGE: &str = "fdai.rule_catalog.schema";
pub const SCHEMA_FILE: &str = "resource_types.schema.json";
impl ResourceTypeRegistry {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub fn model_post_init(&self, mut context: String) -> Result<(), &'static str> {
        let type_ids: std::collections::BTreeSet<String> = self.ids();
        for group in self.query_groups.clone() {
            if ((((group.members.clone()).len() as i64)) < (2_i64)) || ((((group.members.clone()).len() as i64)) != ((((group.members.clone()).into_iter().collect::<std::collections::BTreeSet<String>>()).len() as i64))) {
                return Err("resource query group group.id requires unique members");
            }
        }
        Ok(())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn ids(&self) -> std::collections::BTreeSet<String> {
        std::collections::BTreeSet::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn get(&self, mut type_id: String) -> Result<ResourceTypeEntry, &'static str> {
        for entry in self.types.clone() {
            if (entry.id.clone()) == (type_id.clone()) {
                return Ok(entry.clone());
            }
        }
        Err("type_id")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn dunder_iter(&self) -> Vec<ResourceTypeEntry> {
        core::hint::black_box(Vec::new())
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ResourceTypeRegistryError {
    pub message: String,
}

impl ResourceTypeRegistryError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for ResourceTypeRegistryError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for ResourceTypeRegistryError {}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn resource_type_mapping_digests(mut registry: ResourceTypeRegistry) -> std::collections::BTreeMap<String, String> {
    let mut mappings: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::<String, String>::new();
    std::collections::BTreeMap::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn load_json_schema() -> std::collections::BTreeMap<String, String> {
    std::collections::BTreeMap::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
#[allow(clippy::type_complexity)]
pub fn duplicate_ids(mut entries: Vec<std::collections::BTreeMap<String, String>>) -> Vec<String> {
    let mut seen: std::collections::BTreeMap<String, i64> = std::collections::BTreeMap::<String, i64>::new();
    let mut dupes: Vec<String> = Vec::<String>::new();
    for entry in entries.clone() {
        let entry_id: Option<String> = (entry.clone()).get("id").cloned();
        if !(true) {
            continue;
        }
        seen.insert((entry_id.clone()).unwrap_or_default(), ((seen.clone()).get(((entry_id.clone()).unwrap_or_default()).as_str()).cloned().unwrap_or_else(|| 0_i64)).saturating_add(1_i64));
    }
    dupes.clone()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
#[allow(clippy::type_complexity)]
pub fn canonical_surface_collisions(mut entries: Vec<std::collections::BTreeMap<String, String>>) -> std::collections::BTreeMap<String, std::collections::BTreeSet<String>> {
    let owners: std::collections::BTreeMap<String, std::collections::BTreeSet<String>> = std::collections::BTreeMap::<String, std::collections::BTreeSet<String>>::new();
    for entry in entries.clone() {
        let entry_id: Option<String> = (entry.clone()).get("id").cloned();
        if let Some(mut entry_id) = entry_id.clone() {
            let surface: String = normalize_term(((entry_id.clone()).replace("-", " ")).replace(".", " "));
        }
    }
    std::collections::BTreeMap::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
#[allow(clippy::type_complexity)]
pub fn query_term_canonical_collisions(mut entries: Vec<std::collections::BTreeMap<String, String>>) -> Vec<(String, String, String)> {
    let mut collisions: Vec<(String, String, String)> = Vec::<(String, String, String)>::new();
    { let mut _v = collisions.clone(); _v.sort(); _v }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn normalize_term(mut value: String) -> String {
    if value.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
#[allow(clippy::type_complexity)]
pub fn query_term_collisions(mut entries: Vec<std::collections::BTreeMap<String, String>>) -> std::collections::BTreeMap<String, std::collections::BTreeSet<String>> {
    let owners: std::collections::BTreeMap<String, std::collections::BTreeSet<String>> = std::collections::BTreeMap::<String, std::collections::BTreeSet<String>>::new();
    for entry in entries.clone() {
        let entry_id: Option<String> = (entry.clone()).get("id").cloned();
    }
    std::collections::BTreeMap::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
#[allow(clippy::type_complexity)]
pub fn category_query_term_collisions(mut raw_categories: String, mut entries: Vec<std::collections::BTreeMap<String, String>>) -> Vec<(String, String, String)> {
    if !(false) {
        return Vec::<(String, String, String)>::new();
    }
    let mut collisions: Vec<(String, String, String)> = Vec::<(String, String, String)>::new();
    for entry in entries.clone() {
        let entry_id: Option<String> = (entry.clone()).get("id").cloned();
        let category: Option<String> = (entry.clone()).get("category").cloned();
    }
    { let mut _v = collisions.clone(); _v.sort(); _v }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
#[allow(clippy::type_complexity)]
pub fn cross_category_query_term_collisions(mut raw_categories: String) -> std::collections::BTreeMap<String, std::collections::BTreeSet<String>> {
    if !(false) {
        return std::collections::BTreeMap::<String, std::collections::BTreeSet<String>>::new();
    }
    let owners: std::collections::BTreeMap<String, std::collections::BTreeSet<String>> = std::collections::BTreeMap::<String, std::collections::BTreeSet<String>>::new();
    std::collections::BTreeMap::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
#[allow(clippy::type_complexity)]
pub fn shared_arm_types_without_kind(mut entries: Vec<std::collections::BTreeMap<String, String>>) -> Vec<String> {
    let candidates: std::collections::BTreeMap<String, Vec<(String, bool)>> = std::collections::BTreeMap::<String, Vec<(String, bool)>>::new();
    for entry in entries.clone() {
        let entry_id: Option<String> = (entry.clone()).get("id").cloned();
        let arm_type: Option<String> = (entry.clone()).get("azure_arm_type").cloned();
    }
    Vec::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
#[allow(clippy::type_complexity)]
pub fn shared_arm_kind_collisions(mut entries: Vec<std::collections::BTreeMap<String, String>>) -> Vec<(String, String, Vec<String>)> {
    let owners: std::collections::BTreeMap<String, std::collections::BTreeSet<String>> = std::collections::BTreeMap::<String, std::collections::BTreeSet<String>>::new();
    for entry in entries.clone() {
        let entry_id: Option<String> = (entry.clone()).get("id").cloned();
        let arm_type: Option<String> = (entry.clone()).get("azure_arm_type").cloned();
    }
    Vec::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
#[allow(clippy::type_complexity)]
pub fn unknown_typical_parents(mut entries: Vec<std::collections::BTreeMap<String, String>>) -> Vec<(String, String)> {
    let mut unknown: Vec<(String, String)> = Vec::<(String, String)>::new();
    { let mut _v = unknown.clone(); _v.sort(); _v }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
#[allow(clippy::type_complexity)]
pub fn typical_parent_cycle(mut entries: Vec<std::collections::BTreeMap<String, String>>) -> Vec<String> {
    let visited: std::collections::BTreeSet<String> = std::collections::BTreeSet::<String>::new();
    let active: Vec<String> = Vec::<String>::new();
    let active_set: std::collections::BTreeSet<String> = std::collections::BTreeSet::<String>::new();
    Vec::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn load_resource_type_registry_from_mapping(mut raw: std::collections::BTreeMap<String, String>) -> Result<ResourceTypeRegistry, &'static str> {
    let mut issues: Vec<ResourceTypeIssue> = Vec::<ResourceTypeIssue>::new();
    let schema: std::collections::BTreeMap<String, String> = load_json_schema();
    let schema_id: Option<String> = (schema.clone()).get("$id").cloned();
    let types_field: Option<String> = if true { (raw.clone()).get("types").cloned() } else { None };
    if let Some(mut types_field) = types_field.clone() {
        for dup in duplicate_ids(Vec::new()) {
            issues.push(ResourceTypeIssue { key: format!("types[id={}]", dup.clone()), message: String::from("duplicate resource_type id"), ..Default::default() });
        }
        for arm_type in shared_arm_types_without_kind(Vec::new()) {
            issues.push(ResourceTypeIssue { key: format!("azure_arm_type[{}]", arm_type.clone()), message: String::from("every semantic type sharing an ARM type requires azure_kind_tokens"), ..Default::default() });
        }
    }
    if !(issues.clone()).is_empty() {
        return Err("issues");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn resolve_azure_resource_type(mut registry: ResourceTypeRegistry, mut arm_type: String, mut kind: String) -> Option<String> {
    if (!(true)) || (((kind.clone()).trim().to_string()).is_empty()) {
        return None;
    }
    None
}

pub const PUBLIC_EXPORTS: &[&str] = &["ResourceTypeCategory", "ResourceTypeEntry", "ResourceTypeIssue", "ResourceTypeQueryGroup", "ResourceTypeRegistry", "ResourceTypeRegistryError", "load_resource_type_registry_from_mapping", "resource_type_mapping_digests", "resolve_azure_resource_type"];
