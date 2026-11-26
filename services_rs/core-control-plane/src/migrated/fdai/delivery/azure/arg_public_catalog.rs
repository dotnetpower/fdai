use std::collections::BTreeMap;
#[derive(Clone, Debug, Default, PartialEq)]
pub struct ArgTableSpec {
    pub table_name: String,
    pub owner_agent: String,
    pub domain: String,
    pub primary_key_column: String,
    pub scope_columns: Vec<String>,
    pub allowed_columns: Vec<String>,
    pub resource_types: Vec<String>,
}

impl ArgTableSpec {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.table_name.trim().is_empty() { return Err("table_name must be non-empty"); }
        if self.owner_agent.trim().is_empty() { return Err("owner_agent must be non-empty"); }
        if self.domain.trim().is_empty() { return Err("domain must be non-empty"); }
        if self.primary_key_column.trim().is_empty() { return Err("primary_key_column must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ArgPublicCatalog {
    pub schema_version: String,
    pub source: String,
    pub tables: BTreeMap<String, ArgTableSpec>,
    #[allow(clippy::type_complexity)]
    pub tables_by_resource_type: BTreeMap<String, Vec<String>>,
    pub arm_schema_types: Vec<String>,
}

pub const ARM_SNAPSHOT_GLOB: &str = "provider-schema-catalog/azure/snapshots/*.json.gz";
pub const VALID_OWNERS: &[&str] = &["Huginn", "Heimdall", "Njord", "Vidar"];
pub const ARG_NJORD_TABLES: &[&str] = &["advisorresources", "quotaresourcechanges", "sportresources"];
impl ArgTableSpec {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn resource_type_count(&self) -> i64 {
        (self.resource_types.clone()).len() as i64
    }
}

impl ArgPublicCatalog {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn total_tables(&self) -> i64 {
        0_i64
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn total_arg_resource_types(&self) -> i64 {
        0_i64
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn total_arm_schema_types(&self) -> i64 {
        (self.arm_schema_types.clone()).len() as i64
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn get_table(&self, mut table_name: String) -> Result<ArgTableSpec, &'static str> {
        if (!(true)) || ((table_name.trim().to_string()).is_empty()) {
            return Err("ARG table_name MUST be non-empty");
        }
        let key: String = (table_name.trim().to_string()).to_lowercase();
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub fn resolve_tables_for_arm_type(&self, mut arm_resource_type: String) -> Result<Vec<String>, &'static str> {
        if (!(true)) || ((arm_resource_type.trim().to_string()).is_empty()) {
            return Err("arm_resource_type MUST be a non-empty string");
        }
        let normalized: String = (arm_resource_type.trim().to_string()).to_lowercase();
        Ok(Vec::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn tables_for_owner(&self, mut owner_agent: String) -> Vec<ArgTableSpec> {
        let clean: String = if true { owner_agent.trim().to_string() } else { String::from("") };
        Vec::new()
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn load_arg_public_catalog(mut repo_root: Option<String>) -> Result<ArgPublicCatalog, &'static str> {
    let mut tables_dict: std::collections::BTreeMap<String, ArgTableSpec> = std::collections::BTreeMap::<String, ArgTableSpec>::new();
    let by_rtype: std::collections::BTreeMap<String, Vec<String>> = std::collections::BTreeMap::<String, Vec<String>>::new();
    let mut arm_types: std::collections::BTreeSet<String> = std::collections::BTreeSet::<String>::new();
    Ok(ArgPublicCatalog::default())
}

pub const PUBLIC_EXPORTS: &[&str] = &["ARG_OBSERVATION_OWNER_BY_SOURCE", "ArgPublicCatalog", "ArgTableSpec", "load_arg_public_catalog"];
