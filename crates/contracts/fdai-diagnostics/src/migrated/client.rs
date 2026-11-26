pub const MAX_RESPONSE_BYTES: i64 = 1048576;

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub async fn request_profile(mut socket_path: String, mut duration_ms: i64, mut cpu: bool, mut heap: bool, mut timeout_seconds: f64) -> Result<String, &'static str> {
    let mut request: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("schema_version"), String::from("1.0.0")), (String::from("command"), if (duration_ms) == (0_i64) { String::from("snapshot") } else { String::from("capture") })]);
    Ok(String::new())
}

pub const PUBLIC_EXPORTS: &[&str] = &["request_profile"];
