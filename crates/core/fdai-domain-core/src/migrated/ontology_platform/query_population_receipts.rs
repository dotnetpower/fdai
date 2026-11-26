#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn population_receipt_fields(mut population: Option<String>, mut object_types: std::collections::BTreeMap<String, String>, mut request: String, mut page_size: i64, mut source_complete: bool, mut source_generation: Option<String>) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    if (false) || ((page_size) < (0_i64)) {
        return Err("population receipt page_size MUST be a non-negative integer");
    }
    let mut fields: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("schema_version"), String::from("1.3.0"))]);
    Ok(fields.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn redacted_identity_count(mut graph: String, mut object_types: std::collections::BTreeMap<String, String>) -> i64 {
    let mut count: i64 = 0_i64;
    count
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn manifest_digest(mut member_ids: Vec<String>) -> String {
    if member_ids.is_empty() {
        return String::new();
    }
    String::new()
}

pub const PUBLIC_EXPORTS: &[&str] = &["population_receipt_fields"];
