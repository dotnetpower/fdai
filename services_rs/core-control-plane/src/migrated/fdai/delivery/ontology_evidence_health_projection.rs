#[derive(Clone, Debug, Default, PartialEq)]
pub struct OntologyEvidenceSourceStatus {
    pub source_kind: String,
    pub source_identity_alias: String,
    pub generation: String,
    pub ontology_release_digest: String,
    pub observed_at: String,
    pub recorded_at: String,
    pub freshness_ceiling_seconds: Option<i64>,
    pub complete: bool,
    pub truncated: bool,
    pub synthetic: bool,
    pub conflicts: Vec<String>,
    pub drop_reasons: Vec<String>,
    pub visible_instance_count: i64,
    pub visible_link_count: i64,
    pub evidence_refs: Vec<String>,
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn build_object_type_evidence_health_projection(mut object_type: String, mut ontology_release_digest: String, mut now: String, mut source: Option<OntologyEvidenceSourceStatus>, mut unavailable_reason: Option<String>) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    if source.is_none() {
        let mut unavailable_reason: String = match unavailable_reason.clone() { Some(_v) if !_v.is_empty() => _v, _ => return Err("unavailable ontology evidence health requires a reason") };
        let mut payload: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("schema_version"), String::from("1.0.0")), (String::from("ontology_release_digest"), ontology_release_digest.clone()), (String::from("object_type"), object_type.clone()), (String::from("availability"), String::from("unavailable")), (String::from("unavailable_reason"), unavailable_reason.clone()), (String::from("source"), String::new()), (String::from("freshness_state"), String::from("unavailable")), (String::from("complete"), String::new()), (String::from("truncated"), String::new()), (String::from("synthetic"), String::new()), (String::from("conflicts"), String::new()), (String::from("drop_reasons"), String::new()), (String::from("visible_instance_count"), String::new()), (String::from("visible_link_count"), String::new()), (String::from("evidence_refs"), String::new()), (String::from("execution_authority"), String::new()), (String::from("mutation_authority"), String::new())]);
        payload.insert(String::from("_revision"), digest(payload.clone()));
        return Ok(payload.clone());
    }
    let mut payload: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("schema_version"), String::from("1.0.0")), (String::from("ontology_release_digest"), ontology_release_digest.clone()), (String::from("object_type"), object_type.clone()), (String::from("availability"), String::from("available")), (String::from("unavailable_reason"), String::new()), (String::from("source"), String::new()), (String::from("freshness_state"), String::new()), (String::from("complete"), String::new()), (String::from("truncated"), String::new()), (String::from("synthetic"), String::new()), (String::from("conflicts"), String::new()), (String::from("drop_reasons"), String::new()), (String::from("visible_instance_count"), String::new()), (String::from("visible_link_count"), String::new()), (String::from("evidence_refs"), String::new()), (String::from("execution_authority"), String::new()), (String::from("mutation_authority"), String::new())]);
    payload.insert(String::from("_revision"), digest(payload.clone()));
    Ok(payload.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn digest(mut value: std::collections::BTreeMap<String, String>) -> String {
    if value.is_empty() {
        return String::new();
    }
    String::new()
}

pub const PUBLIC_EXPORTS: &[&str] = &["OntologyEvidenceSourceStatus", "build_object_type_evidence_health_projection"];
