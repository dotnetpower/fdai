#[derive(Clone, Debug, Default, PartialEq)]
pub struct AnomalyActionCandidate {
    pub event_type: String,
    pub resource_ref: String,
    pub action_type: String,
    pub arguments_json: String,
    pub evidence_ref: String,
    pub observed_at: String,
    pub expires_at: String,
}

impl AnomalyActionCandidate {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.event_type.trim().is_empty() { return Err("event_type must be non-empty"); }
        if self.resource_ref.trim().is_empty() { return Err("resource_ref must be non-empty"); }
        if self.action_type.trim().is_empty() { return Err("action_type must be non-empty"); }
        if self.arguments_json.trim().is_empty() { return Err("arguments_json must be non-empty"); }
        if self.evidence_ref.trim().is_empty() { return Err("evidence_ref must be non-empty"); }
        if self.observed_at.trim().is_empty() { return Err("observed_at must be non-empty"); }
        if self.expires_at.trim().is_empty() { return Err("expires_at must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct AnomalyActionPreparation {
    pub action_id: String,
    pub shadow_only: bool,
    pub quorum_required: i64,
}

impl AnomalyActionCandidate {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub fn arguments(&self) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
        if (((self.arguments_json.clone()).len() as i64)) > (16384_i64) {
            return Err("anomaly action candidate arguments exceed their bound");
        }
        Ok(std::collections::BTreeMap::new())
    }
}

pub trait AnomalyActionSource {
    fn resolve(&self, event_type: String, resource_ref: String) -> String;
}

pub trait AnomalyActionPreparer {
    fn prepare(&self, verdict: std::collections::BTreeMap<String, String>) -> String;
}

