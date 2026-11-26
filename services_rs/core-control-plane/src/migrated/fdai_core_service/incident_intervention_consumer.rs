#[derive(Clone, Debug, Default, PartialEq)]
pub struct IncidentInterventionConsumerBinding {
    pub request_topic: String,
    pub group_id: String,
    pub service: String,
    pub ingress: Option<String>,
}

impl IncidentInterventionConsumerBinding {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.request_topic.trim().is_empty() { return Err("request_topic must be non-empty"); }
        if self.group_id.trim().is_empty() { return Err("group_id must be non-empty"); }
        if self.service.trim().is_empty() { return Err("service must be non-empty"); }
        Ok(())
    }
}

impl IncidentInterventionConsumerBinding {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn run(&self, mut bus: String, mut stop: String) {
        if bus.is_empty() {
            return;
        }
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub async fn consume_incident_interventions(mut bus: String, mut topic: String, mut group_id: String, mut service: String, mut stop: String, mut ingress: Option<String>) -> Result<(), &'static str> {
    if bus.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn incident_intervention_raw_event(mut request: String) -> std::collections::BTreeMap<String, String> {
    std::collections::BTreeMap::from([(String::from("event_type"), String::new()), (String::from("event_id"), String::new()), (String::from("idempotency_key"), String::new()), (String::from("correlation_id"), String::new()), (String::from("source"), String::from("operator-incident-intervention")), (String::from("resource_ref"), String::new()), (String::from("incident_correlation"), String::from("none")), (String::from("occurred_at"), String::new()), (String::from("attributes"), String::new())])
}

pub const PUBLIC_EXPORTS: &[&str] = &["IncidentInterventionConsumerBinding", "consume_incident_interventions", "incident_intervention_raw_event"];
