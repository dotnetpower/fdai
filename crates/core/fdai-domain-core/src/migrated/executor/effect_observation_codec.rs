#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn observation_receipt_to_mapping(mut receipt: String) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    Ok(std::collections::BTreeMap::from([(String::from("schema_version"), String::new()), (String::from("binding"), String::new()), (String::from("quality"), String::new()), (String::from("observation_id"), String::new()), (String::from("outcome"), String::new()), (String::from("disposition"), String::new()), (String::from("reason"), String::new()), (String::from("observer_instance_id"), String::new()), (String::from("executor_instance_id"), String::new()), (String::from("source_instance_id"), String::new()), (String::from("observed_at"), String::new()), (String::from("completed_at"), String::new()), (String::from("sequence"), String::new()), (String::from("prior_receipt_digest"), String::new()), (String::from("receipt_digest"), String::new()), (String::from("effect_verified"), String::new()), (String::from("execution_authority"), String::new()), (String::from("sink_commit_authority"), String::new()), (String::from("lock_release_authority"), String::new()), (String::from("promotion_authority"), String::new())]))
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn observation_receipt_from_mapping(mut value: std::collections::BTreeMap<String, String>) -> String {
    let receipt: std::collections::BTreeMap<String, String> = exact(value.clone(), std::collections::BTreeSet::new(), String::from("receipt")).unwrap_or_else(|_| std::collections::BTreeMap::new());
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn binding_to_mapping(mut binding: String) -> std::collections::BTreeMap<String, String> {
    std::collections::BTreeMap::from([(String::from("schema_version"), String::new()), (String::from("action_id"), String::new()), (String::from("action_payload_digest"), String::new()), (String::from("target_digest"), String::new()), (String::from("source_revision"), String::new()), (String::from("execution_path"), String::new()), (String::from("execution_origin"), String::new()), (String::from("execution_venue"), String::new()), (String::from("safeguard_bundle_digest"), String::new()), (String::from("evidence_identity_digest"), String::new()), (String::from("evidence_record_digest"), String::new()), (String::from("evidence_record_revision"), String::new()), (String::from("executor_receipt_digest"), String::new()), (String::from("binding_digest"), String::new())])
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn binding_from_mapping(mut value: std::collections::BTreeMap<String, String>) -> String {
    let binding: std::collections::BTreeMap<String, String> = exact(value.clone(), std::collections::BTreeSet::new(), String::from("binding")).unwrap_or_else(|_| std::collections::BTreeMap::new());
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn quality_to_mapping(mut quality: String) -> std::collections::BTreeMap<String, String> {
    std::collections::BTreeMap::from([(String::from("schema_version"), String::new()), (String::from("evidence_window_start"), String::new()), (String::from("evidence_window_end"), String::new()), (String::from("source_recorded_at"), String::new()), (String::from("max_source_age_seconds"), String::new()), (String::from("finality"), String::new()), (String::from("completeness"), String::new()), (String::from("containment"), String::new()), (String::from("conflicting_source_count"), String::new()), (String::from("synthetic"), String::new())])
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn quality_from_mapping(mut value: std::collections::BTreeMap<String, String>) -> Result<String, &'static str> {
    let quality: std::collections::BTreeMap<String, String> = exact(value.clone(), std::collections::BTreeSet::new(), String::from("quality")).unwrap_or_else(|_| std::collections::BTreeMap::new());
    let raw_age: Option<String> = (quality.clone()).get("max_source_age_seconds").cloned();
    Ok(String::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn exact(mut value: std::collections::BTreeMap<String, String>, mut expected: std::collections::BTreeSet<String>, mut name: String) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    Ok(value.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn object(mut value: std::collections::BTreeMap<String, String>, mut name: String) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    let field: Option<String> = (value.clone()).get(name.as_str()).cloned();
    Ok(std::collections::BTreeMap::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn text(mut value: std::collections::BTreeMap<String, String>, mut name: String) -> Result<String, &'static str> {
    let field: Option<String> = (value.clone()).get(name.as_str()).cloned();
    Ok((field.clone()).unwrap_or_default())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn optional_text(mut value: std::collections::BTreeMap<String, String>, mut name: String) -> Option<String> {
    if ((value.clone()).get(name.as_str()).cloned()).is_none() {
        return None;
    }
    Some(text(value.clone(), name.clone()).unwrap_or_else(|_| String::new()))
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn integer(mut value: std::collections::BTreeMap<String, String>, mut name: String) -> Result<i64, &'static str> {
    let field: Option<String> = (value.clone()).get(name.as_str()).cloned();
    Ok(0_i64)
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn boolean(mut value: std::collections::BTreeMap<String, String>, mut name: String) -> Result<bool, &'static str> {
    let field: Option<String> = (value.clone()).get(name.as_str()).cloned();
    Ok(false)
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn r#false(mut value: std::collections::BTreeMap<String, String>, mut name: String) -> Result<bool, &'static str> {
    Ok(false)
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn moment(mut value: std::collections::BTreeMap<String, String>, mut name: String) -> Result<String, &'static str> {
    let raw: String = text(value.clone(), name.clone()).unwrap_or_else(|_| String::new());
    Ok(String::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn version(mut value: std::collections::BTreeMap<String, String>) -> Result<String, &'static str> {
    if (text(value.clone(), String::from("schema_version")).unwrap_or_else(|_| String::new())) != (String::from("1.0.0")) {
        return Err("independent effect observation schema version is unsupported");
    }
    Ok(String::from("1.0.0"))
}

pub const PUBLIC_EXPORTS: &[&str] = &["observation_receipt_from_mapping", "observation_receipt_to_mapping"];
