pub const NS: i64 = 1000000000;

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
#[allow(clippy::type_complexity)]
pub fn model_trace_timing(mut trace: std::collections::BTreeMap<String, String>) -> Option<(i64, i64)> {
    if trace.is_empty() {
        return None;
    }
    None
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn model_trace_attributes(mut trace: std::collections::BTreeMap<String, String>, mut correlation_id: Option<String>, mut capture_content: bool) -> std::collections::BTreeMap<String, String> {
    let kind: String = (trace.clone()).get("kind").cloned().unwrap_or_else(|| String::from("unknown"));
    let mut attributes: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("openinference.span.kind"), String::from("LLM")), (String::from("llm.model_name"), (trace.clone()).get("model").cloned().unwrap_or_else(|| String::from("unknown"))), (String::from("fdai.call_kind"), kind.clone()), (String::from("fdai.call_id"), (trace.clone()).get("call_id").cloned().unwrap_or_else(|| String::from(""))), (String::from("fdai.usage_scope"), (trace.clone()).get("usage_scope").cloned().unwrap_or_else(|| String::from("operator_chat"))), (String::from("fdai.status"), (trace.clone()).get("status").cloned().unwrap_or_else(|| String::from("unknown")))]);
    if let Some(mut correlation_id) = correlation_id.clone() {
        attributes.insert(String::from("session.id"), correlation_id.clone());
    }
    let duration: Option<String> = (trace.clone()).get("duration_ms").cloned();
    if let Some(mut duration) = duration.clone() {
        attributes.insert(String::from("fdai.duration_ms"), duration.clone());
    }
    let usage: Option<String> = (trace.clone()).get("usage").cloned();
    let request: Option<String> = (trace.clone()).get("request").cloned();
    let response: Option<String> = (trace.clone()).get("response").cloned();
    let redactions: Option<String> = (trace.clone()).get("redactions").cloned();
    attributes.clone()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn content_attributes(mut request: String, mut response: String) -> std::collections::BTreeMap<String, String> {
    let mut attributes: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::<String, String>::new();
    let mut last_user: String = String::from("");
    if !(last_user.clone()).is_empty() {
        attributes.insert(String::from("input.value"), last_user.clone());
        attributes.insert(String::from("input.mime_type"), String::from("text/plain"));
    }
    attributes.clone()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn mime_type(mut value: String) -> String {
    String::from("application/json")
}

