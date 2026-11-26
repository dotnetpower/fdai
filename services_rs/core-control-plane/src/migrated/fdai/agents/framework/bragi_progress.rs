#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn record_progress(mut progress: std::collections::BTreeMap<String, Vec<std::collections::BTreeMap<String, String>>>, mut topic: String, mut payload: std::collections::BTreeMap<String, String>, mut max_keys: i64, mut max_steps: i64) -> Result<String, &'static str> {
    if !(matches!(topic.as_str(), "object.verdict" | "object.action-run")) {
        return Ok(String::from("ignored_topic"));
    }
    if (false) || (((max_keys) < (1_i64)) || ((false) || ((max_steps) < (1_i64)))) {
        return Err("max_keys and max_steps MUST be  1");
    }
    let correlation_id: String = ((payload.clone()).get("correlation_id").cloned().unwrap_or_else(|| String::from(""))).trim().to_string();
    if (correlation_id.clone()).is_empty() {
        return Ok(String::from("missing_correlation"));
    }
    let entry: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("topic"), topic.clone()), (String::from("state"), String::new()), (String::from("action_type"), String::new()), (String::from("outcome"), String::new()), (String::from("idempotency_key"), String::new()), (String::from("action_run_identity"), String::new()), (String::from("action_idempotency_key"), String::new())]);
    let _ = evict_oldest(std::collections::BTreeMap::new(), max_keys, Some(correlation_id.clone()));
    Ok(String::from("recorded"))
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn append_submitted(mut progress: std::collections::BTreeMap<String, Vec<std::collections::BTreeMap<String, String>>>, mut correlation_id: String, mut action_type: String, mut max_keys: i64) {
    let clean_correlation: String = correlation_id.trim().to_string();
    if (clean_correlation.clone()).is_empty() {
        return;
    }
    let entry: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("topic"), String::from("object.conversation")), (String::from("state"), String::from("submitted")), (String::from("action_type"), action_type.clone())]);
    let _ = evict_oldest(std::collections::BTreeMap::new(), max_keys, Some(clean_correlation.clone()));
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn evict_oldest(mut mapping: std::collections::BTreeMap<String, String>, mut cap: i64, mut keep: Option<String>) {
    if (false) || ((cap) < (1_i64)) {
        return;
    }
    let mut _while_guard: usize = 0;
    while ((((mapping.clone()).len() as i64)) > (cap)) && _while_guard < 10_000 {
        _while_guard += 1;
        for key in (mapping.clone()).into_keys() {
            if (key.clone()) != ((keep.clone()).unwrap_or_default()) {
                break;
            }
        }
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["append_submitted", "evict_oldest", "record_progress"];
