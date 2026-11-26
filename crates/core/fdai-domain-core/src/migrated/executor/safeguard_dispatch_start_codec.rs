#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn dispatch_start_checkpoint_to_mapping(mut checkpoint: String) -> std::collections::BTreeMap<String, String> {
    std::collections::BTreeMap::from([(String::from("schema_version"), String::new()), (String::from("evidence_identity_digest"), String::new()), (String::from("bundle_record_digest"), String::new()), (String::from("bundle_record_revision"), String::new()), (String::from("bundle_persistence_receipt_digest"), String::new()), (String::from("in_flight_reservation_receipt"), String::new()), (String::from("prepared_fence"), String::new()), (String::from("in_flight_fence"), String::new()), (String::from("dispatch_started_at"), String::new()), (String::from("checkpoint_digest"), String::new()), (String::from("execution_authority"), String::new()), (String::from("effect_verified"), String::new())])
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn dispatch_start_checkpoint_from_mapping(mut value: std::collections::BTreeMap<String, String>) -> String {
    let checkpoint: std::collections::BTreeMap<String, String> = exact_mapping(value.clone(), std::collections::BTreeSet::from([String::from("schema_version"), String::from("evidence_identity_digest"), String::from("bundle_record_digest"), String::from("bundle_record_revision"), String::from("bundle_persistence_receipt_digest"), String::from("in_flight_reservation_receipt"), String::from("prepared_fence"), String::from("in_flight_fence"), String::from("dispatch_started_at"), String::from("checkpoint_digest"), String::from("execution_authority"), String::from("effect_verified")]), String::from("checkpoint")).unwrap_or_else(|_| std::collections::BTreeMap::new());
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn reservation_receipt_mapping(mut receipt: String) -> std::collections::BTreeMap<String, String> {
    std::collections::BTreeMap::from([(String::from("schema_version"), String::new()), (String::from("prior_record"), String::new()), (String::from("record"), String::new()), (String::from("expected_prior_revision"), String::new()), (String::from("store_receipt_digest"), String::new()), (String::from("recorded_at"), String::new()), (String::from("receipt_digest"), String::new()), (String::from("execution_authority"), String::new()), (String::from("effect_verified"), String::new())])
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn reservation_receipt_from_mapping(mut value: std::collections::BTreeMap<String, String>) -> String {
    let receipt: std::collections::BTreeMap<String, String> = exact_mapping(value.clone(), std::collections::BTreeSet::from([String::from("schema_version"), String::from("prior_record"), String::from("record"), String::from("expected_prior_revision"), String::from("store_receipt_digest"), String::from("recorded_at"), String::from("receipt_digest"), String::from("execution_authority"), String::from("effect_verified")]), String::from("reservation receipt")).unwrap_or_else(|_| std::collections::BTreeMap::new());
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn optional_reservation_record(mut receipt: std::collections::BTreeMap<String, String>) -> Result<Option<String>, &'static str> {
    let raw: Option<String> = (receipt.clone()).get("prior_record").cloned();
    let Some(mut raw) = raw.clone() else { return Ok(None); };
    Ok(None)
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn exact_mapping(mut value: std::collections::BTreeMap<String, String>, mut expected_keys: std::collections::BTreeSet<String>, mut name: String) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    Ok(value.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn mapping_field(mut value: std::collections::BTreeMap<String, String>, mut name: String) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    let field: Option<String> = (value.clone()).get(name.as_str()).cloned();
    Ok(std::collections::BTreeMap::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn str_field(mut value: std::collections::BTreeMap<String, String>, mut name: String) -> Result<String, &'static str> {
    let field: Option<String> = (value.clone()).get(name.as_str()).cloned();
    Ok((field.clone()).unwrap_or_default())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn int_field(mut value: std::collections::BTreeMap<String, String>, mut name: String) -> Result<i64, &'static str> {
    let field: Option<String> = (value.clone()).get(name.as_str()).cloned();
    Ok(0_i64)
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn datetime_field(mut value: std::collections::BTreeMap<String, String>, mut name: String) -> Result<String, &'static str> {
    let field: String = str_field(value.clone(), name.clone()).unwrap_or_else(|_| String::new());
    Ok(String::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn schema_version(mut value: std::collections::BTreeMap<String, String>) -> Result<String, &'static str> {
    if (str_field(value.clone(), String::from("schema_version")).unwrap_or_else(|_| String::new())) != (String::from("1.0.0")) {
        return Err("safeguard dispatch-start schema version is unsupported");
    }
    Ok(String::from("1.0.0"))
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn false_field(mut value: std::collections::BTreeMap<String, String>, mut name: String) -> Result<bool, &'static str> {
    Ok(false)
}

pub const PUBLIC_EXPORTS: &[&str] = &["dispatch_start_checkpoint_from_mapping", "dispatch_start_checkpoint_to_mapping"];
