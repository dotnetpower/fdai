#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn require_actor_and_time(mut actor_oid: String, mut at: Option<String>) -> Result<String, &'static str> {
    let actor: String = actor_oid.trim().to_string();
    if (actor.clone()).is_empty() {
        return Err("incident audit actor_oid MUST be non-empty");
    }
    Ok(actor.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn open_audit_entry(mut incident: String, mut actor_oid: String) -> std::collections::BTreeMap<String, String> {
    let actor: String = require_actor_and_time(actor_oid.clone(), None).unwrap_or_else(|_| String::new());
    std::collections::BTreeMap::from([(String::from("kind"), String::from("incident.open")), (String::from("idempotency_key"), String::new()), (String::from("correlation_id"), String::new()), (String::from("incident_id"), String::new()), (String::from("severity"), String::new()), (String::from("state"), String::new()), (String::from("actor_oid"), actor.clone()), (String::from("opened_at"), String::new()), (String::from("assignee_oid"), String::new()), (String::from("correlation_keys"), String::new()), (String::from("member_event_ids"), String::new())])
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn transition_audit_entry(mut transition: String, mut incident: String, mut target_severity: String) -> std::collections::BTreeMap<String, String> {
    std::collections::BTreeMap::from([(String::from("kind"), String::from("incident.transition")), (String::from("idempotency_key"), String::new()), (String::from("correlation_id"), String::new()), (String::from("incident_id"), String::new()), (String::from("from_state"), String::new()), (String::from("to_state"), String::new()), (String::from("from_severity"), String::new()), (String::from("severity"), String::new()), (String::from("actor_oid"), String::new()), (String::from("at"), String::new()), (String::from("reason"), String::new())])
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn members_audit_entry(mut incident: String, mut added_member_event_ids: Vec<String>, mut actor_oid: String, mut at: String) -> std::collections::BTreeMap<String, String> {
    let actor: String = require_actor_and_time(actor_oid.clone(), Some(at.clone())).unwrap_or_else(|_| String::new());
    std::collections::BTreeMap::from([(String::from("kind"), String::from("incident.members")), (String::from("idempotency_key"), String::new()), (String::from("correlation_id"), String::new()), (String::from("incident_id"), String::new()), (String::from("severity"), String::new()), (String::from("state"), String::new()), (String::from("actor_oid"), actor.clone()), (String::from("at"), String::new()), (String::from("member_event_ids"), String::new())])
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn severity_audit_entry(mut incident: String, mut target_severity: String, mut actor_oid: String, mut at: String) -> std::collections::BTreeMap<String, String> {
    let actor: String = require_actor_and_time(actor_oid.clone(), Some(at.clone())).unwrap_or_else(|_| String::new());
    std::collections::BTreeMap::from([(String::from("kind"), String::from("incident.severity")), (String::from("idempotency_key"), String::new()), (String::from("correlation_id"), String::new()), (String::from("incident_id"), String::new()), (String::from("state"), String::new()), (String::from("from_severity"), String::new()), (String::from("severity"), String::new()), (String::from("actor_oid"), actor.clone()), (String::from("at"), String::new())])
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn assignment_audit_entry(mut incident: String, mut assignee_oid: Option<String>, mut actor_oid: String, mut at: String) -> std::collections::BTreeMap<String, String> {
    let actor: String = require_actor_and_time(actor_oid.clone(), Some(at.clone())).unwrap_or_else(|_| String::new());
    let target: String = (assignee_oid.clone()).unwrap_or_else(|| String::from("unassigned"));
    std::collections::BTreeMap::from([(String::from("kind"), String::from("incident.assigned")), (String::from("idempotency_key"), String::new()), (String::from("correlation_id"), String::new()), (String::from("incident_id"), String::new()), (String::from("severity"), String::new()), (String::from("state"), String::new()), (String::from("from_assignee_oid"), String::new()), (String::from("assignee_oid"), (assignee_oid.clone()).unwrap_or_default()), (String::from("actor_oid"), actor.clone()), (String::from("at"), String::new())])
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn ticket_audit_entry(mut link: String) -> std::collections::BTreeMap<String, String> {
    std::collections::BTreeMap::from([(String::from("kind"), String::from("incident.ticket")), (String::from("idempotency_key"), String::new()), (String::from("correlation_id"), String::new()), (String::from("incident_id"), String::new()), (String::from("provider"), String::new()), (String::from("ticket_id"), String::new()), (String::from("ticket_url"), String::new()), (String::from("actor_oid"), String::new()), (String::from("at"), String::new())])
}

pub const PUBLIC_EXPORTS: &[&str] = &["assignment_audit_entry", "members_audit_entry", "open_audit_entry", "severity_audit_entry", "ticket_audit_entry", "transition_audit_entry"];
