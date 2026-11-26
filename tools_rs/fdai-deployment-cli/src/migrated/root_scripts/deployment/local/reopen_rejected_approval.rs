pub const LOOPBACK_HOSTS: &[&str] = &["127.0.0.1", "::1", "localhost"];
pub const DSN_ENV: &str = "FDAI_STATE_STORE_DSN";
#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn dsn() -> Result<String, &'static str> {
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub async fn run(mut approval_id: String, mut actor: String, mut apply: bool) -> std::collections::BTreeMap<String, String> {
    std::collections::BTreeMap::from([(String::from("mode"), if apply { String::from("apply") } else { String::from("dry-run") }), (String::from("approval_id"), approval_id.clone()), (String::from("outcome"), String::new())])
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn main() -> i64 {
    0_i64
}

