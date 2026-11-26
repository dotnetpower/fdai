#[derive(Clone, Debug, Default, PartialEq)]
pub struct RuntimeCallEndpointWitness {
    pub observation_id: String,
    pub endpoint_role: String,
    pub caller_arm_id: String,
    pub target_arm_id: String,
    pub platform_revision_name: String,
    pub platform_replica_name: String,
    pub source_container_name: String,
    pub source_container_id: String,
    pub observed_at: String,
    pub evidence_ref: String,
}

impl RuntimeCallEndpointWitness {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.observation_id.trim().is_empty() { return Err("observation_id must be non-empty"); }
        if self.endpoint_role.trim().is_empty() { return Err("endpoint_role must be non-empty"); }
        if self.caller_arm_id.trim().is_empty() { return Err("caller_arm_id must be non-empty"); }
        if self.target_arm_id.trim().is_empty() { return Err("target_arm_id must be non-empty"); }
        if self.platform_revision_name.trim().is_empty() { return Err("platform_revision_name must be non-empty"); }
        if self.platform_replica_name.trim().is_empty() { return Err("platform_replica_name must be non-empty"); }
        if self.source_container_name.trim().is_empty() { return Err("source_container_name must be non-empty"); }
        if self.source_container_id.trim().is_empty() { return Err("source_container_id must be non-empty"); }
        if self.observed_at.trim().is_empty() { return Err("observed_at must be non-empty"); }
        if self.evidence_ref.trim().is_empty() { return Err("evidence_ref must be non-empty"); }
        Ok(())
    }
}

impl RuntimeCallEndpointWitness {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn endpoint_arm_id(&self) -> String {
        if (self.endpoint_role.clone()) == (String::from("caller")) { self.caller_arm_id.clone() } else { self.target_arm_id.clone() }
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["RUNTIME_CALL_TELEMETRY_KQL", "RuntimeCallEndpointWitness"];
