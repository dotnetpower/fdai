use std::collections::BTreeMap;
#[derive(Clone, Debug, Default, PartialEq)]
pub struct PromotionGateSpec {
    pub min_shadow_days: i64,
    pub min_samples: i64,
    pub min_accuracy: f64,
    pub max_policy_escapes: i64,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct TierCeilingSpec {
    pub max_autonomy: String,
    pub min_role: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ActionTypeSpec {
    pub name: String,
    pub operation: String,
    pub interfaces: Vec<String>,
    pub rollback_contract: String,
    pub category: String,
    pub description: String,
    pub default_mode: String,
    pub irreversible: bool,
    pub promotion_gate: Box<PromotionGateSpec>,
    pub trigger_kind: String,
    pub execution_path: String,
    pub ceiling_t0: Box<TierCeilingSpec>,
    pub ceiling_t1: Box<TierCeilingSpec>,
    pub ceiling_t2: Box<TierCeilingSpec>,
    pub prod_downgrade_mode: String,
    #[allow(clippy::type_complexity)]
    pub argument_schema: Option<BTreeMap<String, String>>,
    pub version: String,
    pub schema_version: String,
    pub header_comment: Vec<String>,
}

pub const NAME_PATTERN: &str = "^[a-z][a-z0-9_.\\-]{0,79}\\Z";
pub const ALLOWED_CATEGORIES: &[&str] = &["remediation", "ops", "governance"];
pub const ALLOWED_TRIGGERS: &[&str] = &["rule_violation", "operator_request", "both"];
pub const ALLOWED_ROLES: &[&str] = &["reader", "contributor", "approver", "owner"];
pub const ALLOWED_TIER_CEILING: &[&str] = &["enforce_auto", "enforce_hil", "shadow_only"];
#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn render_action_type_yaml(mut spec: ActionTypeSpec) -> String {
    let mut doc: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("schema_version"), spec.schema_version.clone()), (String::from("name"), spec.name.clone()), (String::from("version"), spec.version.clone()), (String::from("operation"), spec.operation.clone()), (String::from("interfaces"), String::new()), (String::from("rollback_contract"), spec.rollback_contract.clone()), (String::from("irreversible"), String::new()), (String::from("default_mode"), spec.default_mode.clone()), (String::from("promotion_gate"), String::new()), (String::from("preconditions"), String::new()), (String::from("stop_conditions"), String::new()), (String::from("blast_radius"), String::new()), (String::from("description"), spec.description.clone()), (String::from("category"), spec.category.clone()), (String::from("trigger_kind"), String::new()), (String::from("execution_path"), spec.execution_path.clone()), (String::from("ceiling_by_tier"), String::new()), (String::from("prod_downgrade"), String::new())]);
    let header: String = render_header(spec.clone());
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn render_header(mut spec: ActionTypeSpec) -> String {
    if (spec.header_comment.clone()).is_empty() {
        return String::from("");
    }
    String::from("\n\".join(f\"# {line}\" for line in spec.header_comment) + \"\n")
}

pub const PUBLIC_EXPORTS: &[&str] = &["ActionTypeSpec", "PromotionGateSpec", "TierCeilingSpec", "render_action_type_yaml"];
