pub const MAX_REASON: i64 = 256;

pub const REHEARSAL_KIND: &str = "rollback_rehearsal_receipt";
pub trait RollbackRehearsalPort {
    fn rehearse(&self, command: std::collections::BTreeMap<String, String>) -> std::collections::BTreeMap<String, String>;
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn unbound_receipt(mut action_type: String, mut contract: String, mut recorded_at: String) -> std::collections::BTreeMap<String, String> {
    build_receipt(action_type.clone(), contract.clone(), String::from("held"), String::from("rehearsal_port_unbound"), recorded_at.clone(), String::from("1.0.0"))
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn build_receipt(mut action_type: String, mut contract: String, mut outcome: String, mut reason: String, mut recorded_at: String, mut rehearsal_version: String) -> std::collections::BTreeMap<String, String> {
    let bounded_reason: String = ((reason.clone()).trim().to_string()).chars().take((MAX_REASON).max(0) as usize).collect::<String>();
    let mut payload: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("producer_principal"), String::from("Vidar")), (String::from("kind"), String::from(REHEARSAL_KIND)), (String::from("correlation_id"), format!("rollback-rehearsal:{}", action_type.clone())), (String::from("resource_id"), format!("action-type:{}", action_type.clone())), (String::from("action_type"), action_type.clone()), (String::from("rollback_contract"), contract.clone()), (String::from("outcome"), outcome.clone()), (String::from("reason"), bounded_reason.clone()), (String::from("recorded_at"), String::new()), (String::from("rehearsal_version"), { let _a = ((rehearsal_version.clone()).trim().to_string()).chars().take((64_i64).max(0) as usize).collect::<String>(); if !_a.is_empty() { _a } else { String::from("1.0.0") } })]);
    payload.insert(String::from("receipt_digest"), digest(payload.clone()));
    payload.clone()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn command(mut action_type: String, mut contract: String) -> std::collections::BTreeMap<String, String> {
    std::collections::BTreeMap::from([(String::from("mode"), String::from("dry_run")), (String::from("action_type"), action_type.clone()), (String::from("rollback_contract"), contract.clone())])
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn digest(mut payload: std::collections::BTreeMap<String, String>) -> String {
    if payload.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn durable_key(mut receipt: std::collections::BTreeMap<String, String>) -> String {
    let action_type: String = ((receipt.clone()).get("action_type").cloned()).unwrap_or_else(|| String::from(""));
    let digest_scope: String = ((receipt.clone()).get("receipt_digest").cloned()).unwrap_or_else(|| String::from("\").removeprefix(\"sha256:"));
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn to_utc(mut value: String) -> Result<String, &'static str> {
    if value.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

