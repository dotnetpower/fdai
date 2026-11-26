#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum AksCommerceStatus {
    #[default]
    CatalogUnavailable,
    DeadLetterGrowth,
    DependencyPressure,
    DeploymentRegression,
    Healthy,
    Held,
    OrderBacklog,
    Recovered,
}

impl AksCommerceStatus {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::CatalogUnavailable => "catalog_unavailable",
            Self::DeadLetterGrowth => "dead_letter_growth",
            Self::DependencyPressure => "dependency_pressure",
            Self::DeploymentRegression => "deployment_regression",
            Self::Healthy => "healthy",
            Self::Held => "held",
            Self::OrderBacklog => "order_backlog",
            Self::Recovered => "recovered",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum AksCommerceEvidenceState {
    #[default]
    Complete,
    Conflicting,
    Stale,
    Unavailable,
}

impl AksCommerceEvidenceState {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Complete => "complete",
            Self::Conflicting => "conflicting",
            Self::Stale => "stale",
            Self::Unavailable => "unavailable",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct AksCommerceMetric {
    pub name: String,
    pub unit: String,
    pub current: Option<f64>,
    pub previous: Option<f64>,
    pub source_ref: String,
    pub observed_at: String,
    pub state: AksCommerceEvidenceState,
    pub synthetic: bool,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct AksCommerceSlo {
    pub slo_id: String,
    pub objective_ratio: f64,
    pub observed_ratio: Option<f64>,
    pub budget_remaining_ratio: Option<f64>,
    pub breached: Option<bool>,
    pub state: AksCommerceEvidenceState,
    pub source_ref: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct AksCommerceWorkload {
    pub workload_id: String,
    pub display_name: String,
    pub resource_ref: Option<String>,
    pub ready: Option<bool>,
    pub revision: Option<String>,
    pub evidence_state: AksCommerceEvidenceState,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct AksCommerceAction {
    pub action_type: String,
    pub state: String,
    pub target_ref: String,
    pub action_run_ref: Option<String>,
    pub execution_authority: bool,
    pub effect_verified: Option<bool>,
    pub effect_evidence_ref: Option<String>,
}

impl AksCommerceAction {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.state.as_str(), "proposed" | "pending_approval" | "approved" | "running" | "completed" | "failed") { return Err("invalid state literal"); }
        if self.execution_authority { return Err("execution_authority violated literal bool invariant"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct AksCommerceProjection {
    pub r#type: String,
    pub schema_version: String,
    pub assessment_id: String,
    pub service_id: String,
    pub status: AksCommerceStatus,
    pub summary: String,
    pub observed_at: String,
    pub window_start: String,
    pub window_end: String,
    pub complete: bool,
    pub synthetic: bool,
    pub affected_workload_ids: Vec<String>,
    pub dependency_path: Vec<String>,
    pub workloads: Vec<AksCommerceWorkload>,
    pub metrics: Vec<AksCommerceMetric>,
    pub slos: Vec<AksCommerceSlo>,
    pub evidence_gaps: Vec<String>,
    pub evidence_refs: Vec<String>,
    #[allow(clippy::type_complexity)]
    pub proposed_action: Option<Box<AksCommerceAction>>,
    pub owner_agent: String,
    pub observer_agent: String,
    pub execution_authority: bool,
}

impl AksCommerceProjection {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.r#type.as_str(), "aks-commerce.projection") { return Err("invalid type literal"); }
        if !matches!(self.schema_version.as_str(), "1.0.0") { return Err("invalid schema_version literal"); }
        if !matches!(self.service_id.as_str(), "order-fulfillment" | "catalog-browse") { return Err("invalid service_id literal"); }
        if !matches!(self.owner_agent.as_str(), "Forseti") { return Err("invalid owner_agent literal"); }
        if !matches!(self.observer_agent.as_str(), "Heimdall") { return Err("invalid observer_agent literal"); }
        if self.execution_authority { return Err("execution_authority violated literal bool invariant"); }
        Ok(())
    }
}

impl AksCommerceMetric {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn validate_metric(&self) -> Result<AksCommerceMetric, &'static str> {
        Err("runtime_binding_required")
    }
}

impl AksCommerceSlo {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn validate_slo(&self) -> Result<AksCommerceSlo, &'static str> {
        Err("runtime_binding_required")
    }
}

impl AksCommerceWorkload {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn validate_workload(&self) -> Result<AksCommerceWorkload, &'static str> {
        Err("runtime_binding_required")
    }
}

impl AksCommerceAction {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn validate_action(&self) -> Result<AksCommerceAction, &'static str> {
        if ((self.state.clone()) != (String::from("completed"))) && (self.effect_verified.is_some()) {
            return Err("nonterminal AKS commerce action cannot claim effect verification");
        }
        Ok(self.clone())
    }
}

impl AksCommerceProjection {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn validate_projection(&self) -> Result<AksCommerceProjection, &'static str> {
        if !(((self.window_start.clone()) < (self.window_end.clone())) && ((self.window_end.clone()) <= (self.observed_at.clone()))) {
            return Err("AKS commerce projection window must end by observation time");
        }
        if ((((self.dependency_path.clone()).into_iter().collect::<std::collections::BTreeSet<String>>()).len() as i64)) != (((self.dependency_path.clone()).len() as i64)) {
            return Err("AKS commerce dependency path must not contain cycles");
        }
        if ((((self.evidence_gaps.clone()).into_iter().collect::<std::collections::BTreeSet<String>>()).len() as i64)) != (((self.evidence_gaps.clone()).len() as i64)) {
            return Err("AKS commerce evidence gaps must be unique");
        }
        if ((((self.evidence_refs.clone()).into_iter().collect::<std::collections::BTreeSet<String>>()).len() as i64)) != (((self.evidence_refs.clone()).len() as i64)) {
            return Err("AKS commerce evidence refs must be unique");
        }
        if (self.complete) == (!(self.evidence_gaps.clone()).is_empty()) {
            return Err("AKS commerce completeness must match empty evidence gaps");
        }
        Ok(self.clone())
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["AksCommerceAction", "AksCommerceEvidenceState", "AksCommerceMetric", "AksCommerceProjection", "AksCommerceSlo", "AksCommerceStatus", "AksCommerceWorkload"];
