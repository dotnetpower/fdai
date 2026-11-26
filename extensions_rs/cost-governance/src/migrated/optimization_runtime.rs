use std::collections::BTreeMap;
#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum OptimizationPublicationState {
    #[default]
    Published,
    Held,
}

impl OptimizationPublicationState {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Published => "published",
            Self::Held => "held",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct OptimizationPublicationResult {
    pub state: OptimizationPublicationState,
    pub reason: String,
    #[allow(clippy::type_complexity)]
    pub candidate: Option<BTreeMap<String, String>>,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct CostOptimizationRuntime {
    pub initialized: bool,
}

impl CostOptimizationRuntime {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::too_many_arguments)]
    pub async fn publish_plan(&self, mut plan: String, mut correlation_id: String, mut observed_at: String, mut cost_objective_id: String, mut effects: Vec<String>, mut evidence_refs: Vec<String>, mut source_freshness: Vec<String>) -> OptimizationPublicationResult {
        self.publish(std::collections::BTreeMap::new()).await
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn publish_reinjection(&self, mut reinjection: String) -> OptimizationPublicationResult {
        self.publish(std::collections::BTreeMap::new()).await
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn publish(&self, mut candidate: std::collections::BTreeMap<String, String>) -> OptimizationPublicationResult {
        OptimizationPublicationResult { reason: String::from("candidate_entered_typed_ingress"), ..Default::default() }
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["CostOptimizationRuntime", "OptimizationPublicationResult", "OptimizationPublicationState"];
