use std::collections::BTreeMap;
#[derive(Clone, Debug, Default, PartialEq)]
pub struct AksCommerceEvidenceFrame {
    pub service_id: String,
    pub observed_at: String,
    pub window_start: String,
    pub window_end: String,
    pub dependency_path: Vec<String>,
    pub workloads: Vec<String>,
    pub slos: Vec<String>,
    pub metrics: Vec<String>,
    pub evidence_refs: Vec<String>,
    pub evidence_gaps: Vec<String>,
    pub deployment_changed: bool,
    pub rollout_stalled: bool,
    pub order_store_pressure: bool,
    pub prior_degraded: bool,
    pub synthetic: bool,
}

impl AksCommerceEvidenceFrame {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.service_id.as_str(), "catalog-browse" | "order-fulfillment") { return Err("invalid service_id literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct AksCommerceAssessmentPolicy {
    pub backlog_growth_minimum: f64,
    pub dead_letter_growth_minimum: f64,
    pub catalog_availability_metric: String,
    pub active_messages_metric: String,
    pub incoming_messages_metric: String,
    pub completed_messages_metric: String,
    pub dead_letter_messages_metric: String,
    #[allow(clippy::type_complexity)]
    pub required_metrics: BTreeMap<String, Vec<String>>,
}

impl AksCommerceEvidenceFrame {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub fn metric(&self, mut name: String) -> Result<Option<String>, &'static str> {
        if name.is_empty() {
            return Err("missing_required_input");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn derived_gaps(&self) -> Vec<String> {
        let mut gaps: Vec<String> = self.evidence_gaps.clone();
        Vec::new()
    }
}

