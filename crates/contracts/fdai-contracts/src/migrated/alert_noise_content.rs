pub const MAX_ALERT_RECORD_BYTES: i64 = 8388608;
pub const MAX_ALERT_RECORD_NODES: i64 = 250000;
pub const MAX_ALERT_RECORD_DEPTH: i64 = 32;

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn canonical_alert_json(mut value: String) -> Result<String, &'static str> {
    let mut count: i64 = 0_i64;
    Ok(String::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn digest_alert_payload(mut value: String) -> String {
    if value.is_empty() {
        return String::new();
    }
    String::new()
}

