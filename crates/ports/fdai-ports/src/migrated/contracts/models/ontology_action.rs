use std::collections::BTreeMap;
#[derive(Clone, Debug, Default, PartialEq)]
pub struct ActionPrecondition {
    pub kind: String,
    pub value: Option<String>,
    pub link_type: Option<String>,
    pub property: Option<String>,
    pub tag: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ActionBlastRadius {
    pub computation: String,
    pub static_bucket: Option<String>,
    pub max_affected_resources: Option<i64>,
    pub traversal_depth: i64,
    pub traversal_links: Vec<String>,
}

impl ActionBlastRadius {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !(1_i64..=5_i64).contains(&self.traversal_depth) { return Err("traversal_depth out of bounds"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct TriggerKindDecl {
    pub kind: String,
    pub restrict_to_scenarios: Vec<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct TierCeiling {
    pub max_autonomy: String,
    pub min_role: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CeilingByTier {
    #[allow(clippy::type_complexity)]
    pub t0: Option<Box<TierCeiling>>,
    #[allow(clippy::type_complexity)]
    pub t1: Option<Box<TierCeiling>>,
    #[allow(clippy::type_complexity)]
    pub t2: Option<Box<TierCeiling>>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ProdDowngrade {
    pub mode: String,
    pub detection_ref: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct OntologyActionType {
    pub schema_version: String,
    pub name: String,
    pub version: String,
    pub operation: String,
    pub interfaces: Vec<String>,
    pub rollback_contract: String,
    pub irreversible: bool,
    pub default_mode: String,
    pub promotion_gate: String,
    pub preconditions: Vec<ActionPrecondition>,
    pub required_evidence_semantic_refs: Vec<String>,
    pub stop_conditions: Vec<String>,
    #[allow(clippy::type_complexity)]
    pub blast_radius: Option<Box<ActionBlastRadius>>,
    pub description: Option<String>,
    pub category: Option<String>,
    #[allow(clippy::type_complexity)]
    pub trigger_kind: Option<Box<TriggerKindDecl>>,
    pub execution_path: Option<String>,
    #[allow(clippy::type_complexity)]
    pub ceiling_by_tier: Option<Box<CeilingByTier>>,
    pub env_scope: String,
    #[allow(clippy::type_complexity)]
    pub prod_downgrade: Option<Box<ProdDowngrade>>,
    #[allow(clippy::type_complexity)]
    pub argument_schema: Option<BTreeMap<String, String>>,
    pub live_probe_ref: Option<String>,
    pub provenance: Option<String>,
    pub semantic: Option<String>,
}

impl ProdDowngrade {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn mode_is_a_downgrade(mut value: String) -> Result<String, &'static str> {
        Ok(value.clone())
    }
}

impl OntologyActionType {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn semantic_rollback_is_explicit(&self) -> Result<OntologyActionType, &'static str> {
        Err("runtime_binding_required")
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["ActionBlastRadius", "ActionPrecondition", "ActionStopCondition", "CeilingByTier", "OntologyActionType", "ProdDowngrade", "TierCeiling", "TriggerKindDecl"];
