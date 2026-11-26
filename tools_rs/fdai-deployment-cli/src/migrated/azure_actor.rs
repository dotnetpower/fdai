#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn actor_digest(mut target_binding: String, mut timeout_seconds: i64, mut runner: String) -> Result<String, &'static str> {
    if target_binding.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

pub const PUBLIC_EXPORTS: &[&str] = &["actor_digest"];
