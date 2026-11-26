#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn project_relationship_evidence(mut evidence: Option<String>, mut cutoff: String, mut evaluated_at: String, mut source_complete: Option<bool>) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    if (source_complete.is_some()) && (!(true)) {
        return Err("relationship evidence source completeness MUST be boolean or null");
    }
    let Some(mut evidence) = evidence.clone() else { return Ok(std::collections::BTreeMap::from([(String::from("status"), String::from("unavailable")), (String::from("evidence_kind"), String::new()), (String::from("verification_status"), String::from("unavailable")), (String::from("source"), String::new()), (String::from("source_property_path"), String::new()), (String::from("mapping_id"), String::new()), (String::from("evidence_method"), String::new()), (String::from("cutoff"), String::new()), (String::from("freshness_ceiling_seconds"), String::new()), (String::from("complete"), String::new()), (String::from("reason"), String::from("provider_relationship_evidence_unavailable"))])); };
    Ok(std::collections::BTreeMap::from([(String::from("status"), String::new()), (String::from("evidence_kind"), String::new()), (String::from("verification_status"), String::from("independently_verified\" if evidence.evidence_kind == \"observation\" else \"configuration_observed")), (String::from("source"), String::new()), (String::from("source_property_path"), String::new()), (String::from("mapping_id"), String::new()), (String::from("evidence_method"), String::new()), (String::from("cutoff"), String::new()), (String::from("freshness_ceiling_seconds"), String::new()), (String::from("complete"), String::new()), (String::from("reason"), String::new())]))
}

pub const PUBLIC_EXPORTS: &[&str] = &["project_relationship_evidence"];
