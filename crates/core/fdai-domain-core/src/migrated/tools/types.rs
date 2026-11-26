use std::collections::BTreeMap;
#[derive(Clone, Debug, Default, PartialEq)]
pub struct CapabilityGate {
    pub requires_tier: Option<String>,
    pub requires_novelty_score: Option<String>,
    pub cost_budget_usd_per_call: Option<f64>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ToolArtifact {
    pub id: String,
    pub version: i64,
    pub description: String,
    pub input_schema: BTreeMap<String, String>,
    pub capability_gate: Box<CapabilityGate>,
    #[allow(clippy::type_complexity)]
    pub allowlist: Option<BTreeMap<String, String>>,
    pub output_wrapper: Option<String>,
    pub default_mode: String,
    pub provider: Option<String>,
    pub provenance_source: String,
}

pub const PUBLIC_EXPORTS: &[&str] = &["CapabilityGate", "ToolArtifact"];
