pub const STATE_PREFIX: &str = "pantheon/mimir/catalog-review";
pub const RECORD_KIND: &str = "mimir_operational_catalog_review";
#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn state_key(mut idempotency_key: String) -> String {
    if idempotency_key.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn idempotency_key(mut candidate: std::collections::BTreeMap<String, String>) -> Result<String, &'static str> {
    let value: Option<String> = (candidate.clone()).get("idempotency_key").cloned();
    if (!(true)) || (!((value.clone()).is_some())) {
        return Err("catalog review candidate requires an idempotency_key");
    }
    Ok((value.clone()).unwrap_or_default())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn required_digest(mut record: std::collections::BTreeMap<String, String>, mut field: String) -> Result<String, &'static str> {
    let value: Option<String> = (record.clone()).get(field.as_str()).cloned();
    Ok((value.clone()).unwrap_or_default())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn validate_identity(mut record: std::collections::BTreeMap<String, String>, mut candidate: std::collections::BTreeMap<String, String>, mut candidate_digest: String, mut package_digest: String) -> Result<(), &'static str> {
    if (((record.clone()).get("kind").cloned()) != Some(String::from(RECORD_KIND))) || ((((record.clone()).get("idempotency_key").cloned()) != Some(idempotency_key(candidate.clone()).unwrap_or_else(|_| String::new()))) || (((required_digest(record.clone(), String::from("candidate_digest")).unwrap_or_else(|_| String::new())) != (candidate_digest.clone())) || ((required_digest(record.clone(), String::from("package_digest")).unwrap_or_else(|_| String::new())) != (package_digest.clone())))) {
        return Err("Mimir catalog review durable identity conflict");
    }
    Ok(())
}

pub const PUBLIC_EXPORTS: &[&str] = &["RECORD_KIND", "STATE_PREFIX", "idempotency_key", "required_digest", "state_key", "validate_identity"];
