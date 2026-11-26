use std::collections::BTreeMap;
#[derive(Clone, Debug, Default, PartialEq)]
pub struct ArgRelationshipMappingSpec {
    pub mapping_id: String,
    pub source_provider_type: String,
    pub target_provider_type: String,
    pub source_property_path: String,
    pub link_type: String,
    pub origin: String,
}

impl ArgRelationshipMappingSpec {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.mapping_id.trim().is_empty() { return Err("mapping_id must be non-empty"); }
        if self.source_provider_type.trim().is_empty() { return Err("source_provider_type must be non-empty"); }
        if self.target_provider_type.trim().is_empty() { return Err("target_provider_type must be non-empty"); }
        if self.source_property_path.trim().is_empty() { return Err("source_property_path must be non-empty"); }
        if self.link_type.trim().is_empty() { return Err("link_type must be non-empty"); }
        if self.origin.trim().is_empty() { return Err("origin must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ArgRelationshipMappingCatalog {
    pub mappings: BTreeMap<String, ArgRelationshipMappingSpec>,
    #[allow(clippy::type_complexity)]
    pub by_source_type: BTreeMap<String, Vec<ArgRelationshipMappingSpec>>,
    pub base_mappings_count: i64,
    pub extended_mappings_count: i64,
}

impl ArgRelationshipMappingCatalog {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn total_mappings(&self) -> i64 {
        0_i64
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn mappings_for_source_type(&self, mut source_provider_type: String) -> Vec<ArgRelationshipMappingSpec> {
        let clean: String = if true { (source_provider_type.trim().to_string()).to_lowercase() } else { String::from("") };
        Vec::new()
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn load_arg_relationship_mapping_catalog(mut repo_root: Option<String>) -> ArgRelationshipMappingCatalog {
    let mut by_id: std::collections::BTreeMap<String, ArgRelationshipMappingSpec> = std::collections::BTreeMap::<String, ArgRelationshipMappingSpec>::new();
    let by_src: std::collections::BTreeMap<String, Vec<ArgRelationshipMappingSpec>> = std::collections::BTreeMap::<String, Vec<ArgRelationshipMappingSpec>>::new();
    ArgRelationshipMappingCatalog::default()
}

pub const PUBLIC_EXPORTS: &[&str] = &["ArgRelationshipMappingCatalog", "ArgRelationshipMappingSpec", "load_arg_relationship_mapping_catalog"];
