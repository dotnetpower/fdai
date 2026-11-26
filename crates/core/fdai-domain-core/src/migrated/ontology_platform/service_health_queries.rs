pub const MAX_ROWS: i64 = 256;

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ServiceHealthObservation {
    pub event_id: String,
    pub event_type: String,
    pub title: String,
    pub level: Option<String>,
    pub status: String,
    pub impact_start_at: String,
    pub observed_at: String,
    pub impacted_resource_count: Option<i64>,
    pub impacted_resource_ref: Option<String>,
    pub resource_name: Option<String>,
    pub resource_type: Option<String>,
    pub resource_group: Option<String>,
    pub region: Option<String>,
    pub impact_status: Option<String>,
    pub event_evidence_ref: String,
    pub impact_evidence_ref: Option<String>,
}

impl ServiceHealthObservation {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.event_id.trim().is_empty() { return Err("event_id must be non-empty"); }
        if self.event_type.trim().is_empty() { return Err("event_type must be non-empty"); }
        if self.title.trim().is_empty() { return Err("title must be non-empty"); }
        if self.status.trim().is_empty() { return Err("status must be non-empty"); }
        if self.impact_start_at.trim().is_empty() { return Err("impact_start_at must be non-empty"); }
        if self.observed_at.trim().is_empty() { return Err("observed_at must be non-empty"); }
        if self.event_evidence_ref.trim().is_empty() { return Err("event_evidence_ref must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ServiceHealthCollection {
    pub observations: Vec<ServiceHealthObservation>,
    pub observed_at: String,
    pub complete: bool,
    pub limitation: Option<String>,
    pub attempt_ref: String,
}

impl ServiceHealthCollection {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.observed_at.trim().is_empty() { return Err("observed_at must be non-empty"); }
        if self.attempt_ref.trim().is_empty() { return Err("attempt_ref must be non-empty"); }
        Ok(())
    }
}

pub const SERVICE_HEALTH_FUNCTION_NAME: &str = "query.subscription_service_health";
pub const SERVICE_HEALTH_MEASURE_CONCEPTS: &[&str] = &["service_health.active_event"];
pub const SERVICE_HEALTH_EVENT_TYPES: &[&str] = &["service_issue", "planned_maintenance", "health_advisory"];
pub trait ServiceHealthReader {
    fn read_active(&self) -> String;
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn service_health_function_type() -> String {
    core::hint::black_box(String::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn service_health_function(mut ontology_release: String, mut reader: String) -> Result<String, &'static str> {
    if ontology_release.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

pub const PUBLIC_EXPORTS: &[&str] = &["SERVICE_HEALTH_EVENT_TYPES", "SERVICE_HEALTH_EVENT_TYPE_MEASURES", "SERVICE_HEALTH_FUNCTION_NAME", "SERVICE_HEALTH_ALL_MEASURE_CONCEPTS", "SERVICE_HEALTH_MEASURE_CONCEPTS", "SERVICE_HEALTH_MAX_OBSERVATIONS", "ServiceHealthCollection", "ServiceHealthObservation", "ServiceHealthReader", "service_health_function", "service_health_function_type"];
