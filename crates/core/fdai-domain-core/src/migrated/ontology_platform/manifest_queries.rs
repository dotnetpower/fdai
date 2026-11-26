pub const MAX_ROWS: i64 = 1000;

pub const ONTOLOGY_MANIFEST_FUNCTION_NAME: &str = "query.manifest";
pub const ONTOLOGY_MANIFEST_PURPOSE: &str = "operations-review";
pub const KINDS: &[&str] = &["action", "function", "interface", "link", "object"];
#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn source_artifact_digest() -> String {
    core::hint::black_box(String::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn ontology_manifest_function_type() -> String {
    core::hint::black_box(String::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn ontology_manifest_function(mut ontology_release: String, mut manifest_for_context: String) -> Result<String, &'static str> {
    if ontology_release.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

pub const PUBLIC_EXPORTS: &[&str] = &["ONTOLOGY_MANIFEST_FUNCTION_NAME", "ONTOLOGY_MANIFEST_PURPOSE", "ManifestForContext", "ontology_manifest_function", "ontology_manifest_function_type"];
