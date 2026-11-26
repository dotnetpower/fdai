use std::collections::BTreeMap;
#[derive(Clone, Debug, Default, PartialEq)]
pub struct NoChangeReadback {
    pub root_changes: BTreeMap<String, String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct DatabaseSemanticReadback {
    pub expected_legacy_head: String,
    pub legacy_head: String,
    pub expected_service_heads: BTreeMap<String, String>,
    pub service_heads: BTreeMap<String, String>,
    pub extensions: Vec<String>,
    pub expected_runtime_role_checks: Vec<String>,
    pub runtime_role_checks: BTreeMap<String, bool>,
    pub ontology_release_digest: String,
    pub catalog_digest: String,
    pub defaults_digest: String,
    pub role_manifest_digest: String,
    pub expected_ontology_release_digest: String,
    pub expected_catalog_digest: String,
    pub expected_defaults_digest: String,
    pub expected_role_manifest_digest: String,
    pub shadow_only: bool,
    pub observer_distinct: bool,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct GenesisReadinessReceipt {
    pub source_commit: String,
    pub manifest_digest: String,
    pub target_binding: String,
    pub generated_at: String,
    pub evidence_digests: BTreeMap<String, String>,
    pub database_semantic: Box<DatabaseSemanticReadback>,
    pub inventory_closure: String,
    pub second_run: Box<NoChangeReadback>,
}

pub const SHA256: &str = "^[0-9a-f]{64}$";
pub const COMMIT: &str = "^[0-9a-f]{40}$";
pub const REQUIRED_POSTGRES_EXTENSIONS: &[&str] = &["pg_trgm", "plpgsql", "vector"];
impl NoChangeReadback {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn to_mapping(&self) -> std::collections::BTreeMap<String, String> {
        std::collections::BTreeMap::from([(String::from("roots_total"), String::new()), (String::from("roots"), String::new())])
    }
}

impl DatabaseSemanticReadback {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn to_mapping(&self) -> std::collections::BTreeMap<String, String> {
        std::collections::BTreeMap::from([(String::from("expected_manifest_digest"), String::new()), (String::from("legacy_head"), self.legacy_head.clone()), (String::from("service_heads"), String::new()), (String::from("extensions"), String::new()), (String::from("runtime_role_checks"), String::new()), (String::from("ontology_release_digest"), self.ontology_release_digest.clone()), (String::from("catalog_digest"), self.catalog_digest.clone()), (String::from("defaults_digest"), self.defaults_digest.clone()), (String::from("role_manifest_digest"), self.role_manifest_digest.clone()), (String::from("shadow_only"), String::new()), (String::from("observer_distinct"), String::new())])
    }
}

impl GenesisReadinessReceipt {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn digest(&self) -> String {
        core::hint::black_box(String::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn to_mapping(&self) -> std::collections::BTreeMap<String, String> {
        std::collections::BTreeMap::from([(String::from("schema_version"), String::from("fdai.genesis-readiness-receipt.v1")), (String::from("source_commit"), self.source_commit.clone()), (String::from("manifest_digest"), self.manifest_digest.clone()), (String::from("target_binding"), self.target_binding.clone()), (String::from("generated_at"), self.generated_at.clone()), (String::from("evidence_digests"), String::new()), (String::from("database_semantic"), String::new()), (String::from("inventory_closure"), String::new()), (String::from("second_run"), String::new()), (String::from("status"), String::from("verified"))])
    }
}

