pub const MAX_RESOURCE_CHARS: i64 = 200;
pub const MAX_SESSION_CHARS: i64 = 200;

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
#[allow(clippy::type_complexity)]
pub fn build_action_proposal(mut session_id: String, mut user_id: String, mut question: String, mut judgment: String, mut action_type_names: Vec<String>, mut initiator_role: Option<String>, mut pipeline_available: bool) -> (Option<std::collections::BTreeMap<String, String>>, std::collections::BTreeMap<String, String>) {
    let params: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("question_ref"), String::new()), (String::from("session_ref"), String::new())]);
    let correlation_id: String = proposal_correlation_id(session_id.clone(), question.clone(), String::new(), String::new(), user_id.clone(), params.clone());
    if !(pipeline_available) {
        return (None, std::collections::BTreeMap::from([(String::from("submitted"), String::new()), (String::from("abstain_reason"), String::from("requires_typed_pipeline")), (String::from("correlation_id"), correlation_id.clone()), (String::from("action_type"), String::new())]));
    }
    let proposal: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("idempotency_key"), correlation_id.clone()), (String::from("correlation_id"), correlation_id.clone()), (String::from("initiator_principal"), user_id.clone()), (String::from("operator_initiated"), String::new()), (String::from("action_type"), String::new()), (String::from("resource_id"), String::new()), (String::from("event_type"), String::from("operator_request")), (String::from("params"), String::new())]);
    (Some(proposal.clone()), std::collections::BTreeMap::from([(String::from("submitted"), String::new()), (String::from("correlation_id"), correlation_id.clone()), (String::from("action_type"), String::new()), (String::from("initiator_principal"), user_id.clone())]))
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn proposal_correlation_id(mut session_id: String, mut question: String, mut action_type: String, mut resource_id: String, mut initiator_principal: String, mut params: std::collections::BTreeMap<String, String>) -> String {
    let body: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("session_id"), (session_id.clone()).chars().take((MAX_SESSION_CHARS).max(0) as usize).collect::<String>()), (String::from("turn"), String::new()), (String::from("action_type"), action_type.clone()), (String::from("resource_id"), (resource_id.clone()).chars().take((MAX_RESOURCE_CHARS).max(0) as usize).collect::<String>()), (String::from("initiator_principal"), String::new()), (String::from("params_digest"), String::new())]);
    String::new()
}

pub const PUBLIC_EXPORTS: &[&str] = &["build_action_proposal"];
