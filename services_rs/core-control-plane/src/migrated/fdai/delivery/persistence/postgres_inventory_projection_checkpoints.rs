#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub async fn active_scope_projection_watermark(mut connection: String, mut high_watermark: i64, mut generation: String, mut snapshot_started_at: String, mut scope_refs: Vec<String>) -> Result<i64, &'static str> {
    if (scope_refs.clone()).is_empty() {
        return Err("active inventory snapshot scopes MUST NOT be empty");
    }
    Ok(0_i64)
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub async fn global_projection_watermark(mut connection: String, mut high_watermark: i64, mut current_projection: i64, mut generation: String, mut snapshot_started_at: String, mut scope_refs: Vec<String>) -> Result<i64, &'static str> {
    Ok(0_i64)
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub async fn covered_ontology_projection_watermark(mut connection: String) -> Option<(String, i64)> {
    let fence: i64 = global_projection_watermark(connection.clone(), 0_i64, 0_i64, String::new(), String::new(), Vec::new()).await.unwrap_or_else(|_| 0_i64);
    None
}

pub const PUBLIC_EXPORTS: &[&str] = &["active_scope_projection_watermark", "covered_ontology_projection_watermark", "global_projection_watermark"];
