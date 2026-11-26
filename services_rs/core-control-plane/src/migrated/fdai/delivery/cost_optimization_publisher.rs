#[derive(Clone, Debug, Default, PartialEq)]
pub struct EventBusCostOptimizationCandidatePublisher {
    pub bus: String,
    pub topic: String,
}

impl EventBusCostOptimizationCandidatePublisher {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn publish_cost_optimization_candidate(&self, mut candidate: std::collections::BTreeMap<String, String>, mut activation_revision: i64) -> Result<(), &'static str> {
        if (!(true)) || (((self.topic.clone()).trim().to_string()).is_empty()) {
            return Err("optimization ingress topic MUST be non-empty");
        }
        if (false) || ((!(true)) || ((activation_revision) < (0_i64))) {
            return Err("optimization ingress activation revision MUST be non-negative");
        }
        if (candidate.clone()).contains_key("producer_principal") {
            return Err("optimization ingress MUST NOT supply an agent principal");
        }
        Ok(())
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["EventBusCostOptimizationCandidatePublisher"];
