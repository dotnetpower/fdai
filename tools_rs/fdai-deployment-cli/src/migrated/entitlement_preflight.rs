pub const TRIAL: &str = "trial";
pub const KEY_HOLDER: &str = "key-holder";
#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn select_entitlement_mode() -> Result<String, &'static str> {
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn describe_entitlement_mode(mut mode: String) -> String {
    if mode.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn ensure_azure_session(mut timeout_seconds: i64) -> Result<(), &'static str> {
    Err("runtime_binding_required")
}

pub const PUBLIC_EXPORTS: &[&str] = &["describe_entitlement_mode", "ensure_azure_session", "select_entitlement_mode"];
