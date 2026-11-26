#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn safeguard_dispatch_record_to_mapping(mut record: String) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    Ok(std::collections::BTreeMap::from([(String::from("schema_version"), String::new()), (String::from("identity"), String::new()), (String::from("bundle"), String::new()), (String::from("state"), String::new()), (String::from("revision"), String::new()), (String::from("prior_record_digest"), String::new()), (String::from("dispatch_start_checkpoint"), String::new()), (String::from("dispatch_observation"), String::new()), (String::from("pre_release_checkpoint"), String::new()), (String::from("independent_effect_state"), String::new()), (String::from("state_changed_at"), String::new()), (String::from("record_digest"), String::new()), (String::from("execution_authority"), String::new()), (String::from("effect_verified"), String::new())]))
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn safeguard_dispatch_record_from_mapping(mut value: std::collections::BTreeMap<String, String>) -> String {
    let record: std::collections::BTreeMap<String, String> = exact_mapping(value.clone(), std::collections::BTreeSet::from([String::from("schema_version"), String::from("identity"), String::from("bundle"), String::from("state"), String::from("revision"), String::from("prior_record_digest"), String::from("dispatch_start_checkpoint"), String::from("dispatch_observation"), String::from("pre_release_checkpoint"), String::from("independent_effect_state"), String::from("state_changed_at"), String::from("record_digest"), String::from("execution_authority"), String::from("effect_verified")]), String::from("record")).unwrap_or_else(|_| std::collections::BTreeMap::new());
    let bundle_raw: std::collections::BTreeMap<String, String> = mapping_field(record.clone(), String::from("bundle")).unwrap_or_else(|_| std::collections::BTreeMap::new());
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn identity_mapping(mut identity: String) -> std::collections::BTreeMap<String, String> {
    let mut mapping: std::collections::BTreeMap<String, String> = identity_base_mapping(identity.clone());
    mapping.clone()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn identity_base_mapping(mut identity: String) -> std::collections::BTreeMap<String, String> {
    std::collections::BTreeMap::from([(String::from("schema_version"), String::new()), (String::from("action_id"), String::new()), (String::from("target_digest"), String::new()), (String::from("target_fence_identity_digest"), String::new()), (String::from("target_fence_record_digest"), String::new()), (String::from("target_fence_generation"), String::new()), (String::from("target_fence_revision"), String::new()), (String::from("reservation_identity_digest"), String::new()), (String::from("reservation_attempt"), String::new()), (String::from("acquisition_receipt_digest"), String::new()), (String::from("reservation_receipt_digest"), String::new()), (String::from("reservation_record_digest"), String::new()), (String::from("reservation_revision"), String::new()), (String::from("reservation_lease_expires_at"), String::new()), (String::from("audit_append_receipt_digest"), String::new()), (String::from("lock_assessment_digest"), String::new()), (String::from("lock_assessment_valid_until"), String::new()), (String::from("lock_proof_digest"), String::new()), (String::from("idempotency_proof_digest"), String::new()), (String::from("audit_intent_proof_digest"), String::new()), (String::from("pre_bundle_commitment_digest"), String::new()), (String::from("lock_verifier_id"), String::new()), (String::from("lock_verifier_version"), String::new()), (String::from("lock_trust_anchor_id"), String::new()), (String::from("safeguard_bundle_digest"), String::new()), (String::from("continuity_policy_digest"), String::new()), (String::from("execution_path"), String::new()), (String::from("execution_fingerprint"), String::new()), (String::from("source_revision"), String::new()), (String::from("client_correlation_id"), String::new()), (String::from("sink_idempotency_key"), String::new()), (String::from("identity_digest"), String::new()), (String::from("execution_authority"), String::new()), (String::from("effect_verification_authority"), String::new())])
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn identity_from_mapping(mut value: std::collections::BTreeMap<String, String>) -> String {
    let identity: std::collections::BTreeMap<String, String> = exact_mapping(value.clone(), identity_keys(value.clone()), String::from("identity")).unwrap_or_else(|_| std::collections::BTreeMap::new());
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn identity_keys(mut value: std::collections::BTreeMap<String, String>) -> std::collections::BTreeSet<String> {
    let raw: Option<String> = (value.clone()).get("schema_version").cloned();
    std::collections::BTreeSet::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn identity_schema_version(mut value: std::collections::BTreeMap<String, String>) -> Result<String, &'static str> {
    let raw: String = str_field(value.clone(), String::from("schema_version")).unwrap_or_else(|_| String::new());
    if (raw.clone()) == (String::from("1.0.0")) {
        return Ok(String::from("1.0.0"));
    }
    if (raw.clone()) == (String::from("1.1.0")) {
        return Ok(String::from("1.1.0"));
    }
    Err("safeguard dispatch schema version is unsupported")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn observation_mapping(mut observation: String) -> std::collections::BTreeMap<String, String> {
    std::collections::BTreeMap::from([(String::from("schema_version"), String::new()), (String::from("evidence_identity_digest"), String::new()), (String::from("bundle_record_digest"), String::new()), (String::from("bundle_record_revision"), String::new()), (String::from("dispatch_start_record_digest"), String::new()), (String::from("dispatch_start_record_revision"), String::new()), (String::from("in_flight_reservation_receipt_digest"), String::new()), (String::from("target_fence_record_digest"), String::new()), (String::from("target_fence_revision"), String::new()), (String::from("transport_state"), String::new()), (String::from("sink_state"), String::new()), (String::from("sink_operation_reference_digest"), String::new()), (String::from("authoritative_status_digest"), String::new()), (String::from("dispatch_started_at"), String::new()), (String::from("observed_at"), String::new()), (String::from("observation_digest"), String::new()), (String::from("execution_authority"), String::new()), (String::from("effect_verified"), String::new())])
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn observation_from_mapping(mut value: std::collections::BTreeMap<String, String>) -> String {
    let observation: std::collections::BTreeMap<String, String> = exact_mapping(value.clone(), std::collections::BTreeSet::from([String::from("schema_version"), String::from("evidence_identity_digest"), String::from("bundle_record_digest"), String::from("bundle_record_revision"), String::from("dispatch_start_record_digest"), String::from("dispatch_start_record_revision"), String::from("in_flight_reservation_receipt_digest"), String::from("target_fence_record_digest"), String::from("target_fence_revision"), String::from("transport_state"), String::from("sink_state"), String::from("sink_operation_reference_digest"), String::from("authoritative_status_digest"), String::from("dispatch_started_at"), String::from("observed_at"), String::from("observation_digest"), String::from("execution_authority"), String::from("effect_verified")]), String::from("dispatch observation")).unwrap_or_else(|_| std::collections::BTreeMap::new());
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn checkpoint_mapping(mut checkpoint: String) -> std::collections::BTreeMap<String, String> {
    std::collections::BTreeMap::from([(String::from("schema_version"), String::new()), (String::from("evidence_identity_digest"), String::new()), (String::from("continuity_state"), String::new()), (String::from("acquisition_receipt_digest"), String::new()), (String::from("assessment_digest"), String::new()), (String::from("verifier_id"), String::new()), (String::from("verifier_version"), String::new()), (String::from("trust_anchor_id"), String::new()), (String::from("evaluated_at"), String::new()), (String::from("valid_until"), String::new()), (String::from("rejection_reasons"), String::new()), (String::from("unproven_reason"), String::new()), (String::from("observed_at"), String::new()), (String::from("checkpoint_digest"), String::new()), (String::from("execution_authority"), String::new()), (String::from("effect_verified"), String::new())])
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn checkpoint_from_mapping(mut value: std::collections::BTreeMap<String, String>) -> Result<String, &'static str> {
    let checkpoint: std::collections::BTreeMap<String, String> = exact_mapping(value.clone(), std::collections::BTreeSet::from([String::from("schema_version"), String::from("evidence_identity_digest"), String::from("continuity_state"), String::from("acquisition_receipt_digest"), String::from("assessment_digest"), String::from("verifier_id"), String::from("verifier_version"), String::from("trust_anchor_id"), String::from("evaluated_at"), String::from("valid_until"), String::from("rejection_reasons"), String::from("unproven_reason"), String::from("observed_at"), String::from("checkpoint_digest"), String::from("execution_authority"), String::from("effect_verified")]), String::from("pre-release checkpoint")).unwrap_or_else(|_| std::collections::BTreeMap::new());
    let reasons: Option<String> = (checkpoint.clone()).get("rejection_reasons").cloned();
    Ok(String::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn optional_observation(mut record: std::collections::BTreeMap<String, String>) -> Result<Option<String>, &'static str> {
    let raw: Option<String> = (record.clone()).get("dispatch_observation").cloned();
    let Some(mut raw) = raw.clone() else { return Ok(None); };
    Ok(Some(observation_from_mapping(std::collections::BTreeMap::new())))
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn optional_dispatch_start(mut record: std::collections::BTreeMap<String, String>) -> Result<Option<String>, &'static str> {
    let raw: Option<String> = (record.clone()).get("dispatch_start_checkpoint").cloned();
    let Some(mut raw) = raw.clone() else { return Ok(None); };
    Ok(None)
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn optional_checkpoint(mut record: std::collections::BTreeMap<String, String>) -> Result<Option<String>, &'static str> {
    let raw: Option<String> = (record.clone()).get("pre_release_checkpoint").cloned();
    let Some(mut raw) = raw.clone() else { return Ok(None); };
    Ok(Some(checkpoint_from_mapping(std::collections::BTreeMap::new()).unwrap_or_else(|_| String::new())))
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
#[allow(clippy::type_complexity)]
pub fn optional_str_field(mut value: std::collections::BTreeMap<String, String>, mut name: String) -> Result<Option<String>, &'static str> {
    let field: Option<String> = (value.clone()).get(name.as_str()).cloned();
    let Some(mut field) = field.clone() else { return Ok(None); };
    Ok(Some(field.clone()))
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
#[must_use]
pub fn optional_datetime_field(mut value: std::collections::BTreeMap<String, String>, mut name: String) -> Option<String> {
    if ((value.clone()).get(name.as_str()).cloned()).is_none() {
        return None;
    }
    Some(datetime_field(value.clone(), name.clone()).unwrap_or_else(|_| String::new()))
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn schema_version(mut value: std::collections::BTreeMap<String, String>) -> Result<String, &'static str> {
    if (str_field(value.clone(), String::from("schema_version")).unwrap_or_else(|_| String::new())) != (String::from("1.0.0")) {
        return Err("safeguard dispatch schema version is unsupported");
    }
    Ok(String::from("1.0.0"))
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn pending_field(mut value: std::collections::BTreeMap<String, String>) -> Result<String, &'static str> {
    if (str_field(value.clone(), String::from("independent_effect_state")).unwrap_or_else(|_| String::new())) != (String::from("pending")) {
        return Err("safeguard dispatch independent effect state is invalid");
    }
    Ok(String::from("pending"))
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn false_field(mut value: std::collections::BTreeMap<String, String>, mut name: String) -> Result<bool, &'static str> {
    Ok(false)
}

pub const PUBLIC_EXPORTS: &[&str] = &["safeguard_dispatch_record_from_mapping", "safeguard_dispatch_record_to_mapping"];
