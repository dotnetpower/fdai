pub const TRACE_CONTINUITY_EVENT: &str = "trace-continuity.discontinuity";
pub const SEVERITIES: &[&str] = &["critical", "high", "medium", "low", "info"];
#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn evict_oldest(mut mapping: std::collections::BTreeMap<String, String>, mut cap: i64, mut keep: String) {
    let mut _while_guard: usize = 0;
    while ((((mapping.clone()).len() as i64)) > (cap)) && _while_guard < 10_000 {
        _while_guard += 1;
        for key in (mapping.clone()).into_keys() {
            if (key.clone()) != (keep.clone()) {
                break;
            }
        }
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn trace_continuity_evidence(mut event: std::collections::BTreeMap<String, String>) -> std::collections::BTreeMap<String, String> {
    if ((event.clone()).get("event_type").cloned()) != Some(String::from(TRACE_CONTINUITY_EVENT)) {
        return std::collections::BTreeMap::<String, String>::new();
    }
    let attributes: Option<String> = (event.clone()).get("attributes").cloned();
    if !(true) {
        return std::collections::BTreeMap::<String, String>::new();
    }
    std::collections::BTreeMap::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn event_severity(mut event: std::collections::BTreeMap<String, String>) -> String {
    let attributes: Option<String> = (event.clone()).get("attributes").cloned();
    String::new()
}

pub const PUBLIC_EXPORTS: &[&str] = &["TRACE_CONTINUITY_REASONS", "event_severity", "evict_oldest", "trace_continuity_evidence"];
