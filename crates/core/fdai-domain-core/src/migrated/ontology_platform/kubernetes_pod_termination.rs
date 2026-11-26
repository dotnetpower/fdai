pub const MAX_ID_LENGTH: i64 = 512;

#[derive(Clone, Debug, Default, PartialEq)]
pub struct PodTerminationObservation {
    pub pod_uid: String,
    pub cluster_id: String,
    pub namespace: String,
    pub event_type: Option<String>,
    pub reason: Option<String>,
    pub exit_code: Option<i64>,
    pub signal: Option<i64>,
    pub finished_at: Option<String>,
    pub event_time: Option<String>,
    pub recorded_at: Option<String>,
    pub source_identity: Option<String>,
    pub source_revision: Option<String>,
    pub evidence_refs: Vec<String>,
}

impl PodTerminationObservation {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.pod_uid.trim().is_empty() { return Err("pod_uid must be non-empty"); }
        if self.cluster_id.trim().is_empty() { return Err("cluster_id must be non-empty"); }
        if self.namespace.trim().is_empty() { return Err("namespace must be non-empty"); }
        Ok(())
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn is_termination_unavailable_reason(mut value: String) -> bool {
    if value.is_empty() {
        return false;
    }
    false
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn termination_unavailable_gap(mut reason: String) -> String {
    format!("termination_kubernetes_lifecycle_{}", reason.clone())
}

pub const PUBLIC_EXPORTS: &[&str] = &["PodTerminationObservation", "PodTerminationUnavailableReason", "is_termination_unavailable_reason", "termination_unavailable_gap"];
