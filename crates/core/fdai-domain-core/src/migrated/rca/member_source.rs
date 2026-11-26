use std::collections::BTreeMap;
#[derive(Clone, Debug, Default, PartialEq)]
pub struct IncidentRcaContext {
    pub members: Vec<String>,
    #[allow(clippy::type_complexity)]
    pub depends_on: BTreeMap<String, Vec<String>>,
    pub inventory_generation: String,
    pub graph_revision: Option<String>,
    pub evidence_refs: Vec<String>,
}

impl IncidentRcaContext {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.inventory_generation.trim().is_empty() { return Err("inventory_generation must be non-empty"); }
        Ok(())
    }
}

pub trait IncidentMemberSource {
    fn members(&self, incident_id: String) -> Vec<String>;
}

pub trait IncidentRcaContextSource {
    fn context(&self, incident_id: String, resource_ref: String, event_type: String, correlation_id: Option<String>, detected_at: String) -> String;
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct NoopIncidentMemberSource {
    pub initialized: bool,
}

impl NoopIncidentMemberSource {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn members(&self, mut incident_id: String) -> Vec<String> {
        if !self.initialized {
            return Vec::new();
        }
        Vec::new()
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["IncidentMemberSource", "IncidentRcaContext", "IncidentRcaContextSource", "NoopIncidentMemberSource"];
