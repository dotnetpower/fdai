pub const CONFIGURED: bool = false;
#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn configure_tracing(mut service_name: String, mut env: String, mut otlp_endpoint: Option<String>, mut otlp_insecure: bool) {
    if CONFIGURED {
        return;
    }
    let configured: bool = true;
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn get_tracer(mut name: String) -> String {
    if name.is_empty() {
        return String::new();
    }
    String::new()
}

pub const PUBLIC_EXPORTS: &[&str] = &["configure_tracing", "get_tracer"];
