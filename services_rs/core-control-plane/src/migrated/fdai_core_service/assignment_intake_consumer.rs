#[derive(Clone, Debug, Default, PartialEq)]
pub struct AssignmentIntakeConsumer {
    pub intake: String,
    pub ingress: Option<String>,
    pub clock: String,
}

impl AssignmentIntakeConsumer {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn run(&self, mut bus: String, mut stop: String) -> Result<(), &'static str> {
        if bus.is_empty() {
            return Err("missing_required_input");
        }
        Err("runtime_binding_required")
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn assignment_raw_event(mut notice: String) -> std::collections::BTreeMap<String, String> {
    let attributes: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("assignment_notice"), String::new())]);
    std::collections::BTreeMap::from([(String::from("event_type"), String::new()), (String::from("event_id"), String::new()), (String::from("idempotency_key"), String::new()), (String::from("correlation_id"), String::new()), (String::from("source"), String::from("operator-assignment-receipt")), (String::from("incident_correlation"), String::from("none")), (String::from("attributes"), String::new())])
}

pub const PUBLIC_EXPORTS: &[&str] = &["AssignmentIntakeConsumer", "assignment_raw_event"];
