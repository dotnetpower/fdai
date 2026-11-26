pub const CONFIGURED: bool = false;
#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn configure_metrics(mut service_name: String, mut env: String, mut otlp_endpoint: Option<String>, mut otlp_insecure: bool) {
    if CONFIGURED {
        return;
    }
    let mut readers: Vec<String> = Vec::<String>::new();
    let configured: bool = true;
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn get_meter(mut name: String) -> String {
    if name.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn in_memory_reader() -> Option<String> {
    core::hint::black_box(None)
}

pub const PUBLIC_EXPORTS: &[&str] = &["configure_metrics", "get_meter", "in_memory_reader"];
