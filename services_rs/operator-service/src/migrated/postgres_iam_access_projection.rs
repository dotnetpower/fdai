#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn access_request_from_proposal(mut value: std::collections::BTreeMap<String, String>) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    let payload: Option<String> = (value.clone()).get("payload").cloned();
    if !(true) {
        return Err("stored access-request proposal payload is malformed");
    }
    let proposal_id: Option<String> = (value.clone()).get("proposal_id").cloned();
    let accepted_at: Option<String> = (value.clone()).get("accepted_at").cloned();
    let required: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("idempotency_key"), String::new()), (String::from("identity_provider"), String::new()), (String::from("target_subject_id"), String::new()), (String::from("target_username"), String::new()), (String::from("operation"), String::new()), (String::from("role"), String::new()), (String::from("justification"), String::new())]);
    Ok(std::collections::BTreeMap::from([(String::from("request_id"), (proposal_id.clone()).unwrap_or_default()), (String::from("requester_oid"), String::new()), (String::from("requested_at"), (accepted_at.clone()).unwrap_or_default()), (String::from("status"), String::from("pending")), (String::from("reviewed_by"), String::new()), (String::from("reviewed_at"), String::new()), (String::from("review_justification"), String::new()), (String::from("proposal_id"), (proposal_id.clone()).unwrap_or_default()), (String::from("dispatch_status"), (value.clone()).get("dispatch_status").cloned().unwrap_or_else(|| String::from("pending")))]))
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn assignment_case_from_proposal(mut value: std::collections::BTreeMap<String, String>) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    let payload: Option<String> = (value.clone()).get("payload").cloned();
    let proposal_id: Option<String> = (value.clone()).get("proposal_id").cloned();
    if (!(true)) || (!(true)) {
        return Err("stored assignment proposal is malformed");
    }
    Ok(std::collections::BTreeMap::from([(String::from("case_id"), (proposal_id.clone()).unwrap_or_default()), (String::from("intent"), String::new()), (String::from("state"), String::from("draft")), (String::from("revision"), String::new()), (String::from("reviews"), String::new()), (String::from("effect_receipts"), String::new()), (String::from("degraded_reason"), String::new()), (String::from("superseded_by"), String::new())]))
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn project_assignment_case(mut assignment: std::collections::BTreeMap<String, String>, mut submitted: Option<std::collections::BTreeMap<String, String>>, mut reviews: Vec<std::collections::BTreeMap<String, String>>) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    let mut projected: std::collections::BTreeMap<String, String> = assignment.clone();
    let Some(mut submitted) = submitted.clone() else { return Ok(projected.clone()); };
    projected.insert(String::from("state"), String::from("pending_review"));
    let mut projected_reviews: Vec<std::collections::BTreeMap<String, String>> = Vec::<std::collections::BTreeMap<String, String>>::new();
    let mut rejected: bool = false;
    let intent: Option<String> = (projected.clone()).get("intent").cloned();
    if rejected {
        projected.insert(String::from("state"), String::from("rejected"));
    }
    Ok(projected.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn assignment_projection_item(mut assignment: std::collections::BTreeMap<String, String>) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    let intent: Option<String> = (assignment.clone()).get("intent").cloned();
    if !(true) {
        return Err("assignment projection intent is malformed");
    }
    Ok(std::collections::BTreeMap::from([(String::from("subject"), String::new()), (String::from("roles"), String::new()), (String::from("duties"), String::new()), (String::from("coverage"), String::new()), (String::from("case"), String::new()), (String::from("handover"), String::new())]))
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn reviewed_access_request(mut request: std::collections::BTreeMap<String, String>, mut review: std::collections::BTreeMap<String, String>) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    let payload: Option<String> = (review.clone()).get("payload").cloned();
    if !(true) {
        return Err("stored access-review proposal payload is malformed");
    }
    let accepted_at: Option<String> = (review.clone()).get("accepted_at").cloned();
    Ok(std::collections::BTreeMap::from([(String::from("status"), String::from("approved\" if decision == \"approve\" else \"rejected")), (String::from("reviewed_by"), String::new()), (String::from("reviewed_at"), (accepted_at.clone()).unwrap_or_default()), (String::from("review_justification"), String::new())]))
}

