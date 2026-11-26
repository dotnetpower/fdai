#[derive(Clone, Debug, Default, PartialEq)]
pub struct WaraRuleCapability {
    pub canonical_resource_type: String,
    pub child_resource_behavior: String,
    pub inventory_fields: Vec<String>,
    pub inventory_source: String,
    pub parameters: String,
    pub eligible_set: String,
    pub failure_semantics: String,
}

impl WaraRuleCapability {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.child_resource_behavior.as_str(), "none") { return Err("invalid child_resource_behavior literal"); }
        if !matches!(self.inventory_source.as_str(), "azure_resource_graph_row") { return Err("invalid inventory_source literal"); }
        if !matches!(self.parameters.as_str(), "none") { return Err("invalid parameters literal"); }
        if !matches!(self.eligible_set.as_str(), "every_resource_of_type") { return Err("invalid eligible_set literal"); }
        if !matches!(self.failure_semantics.as_str(), "absent_or_not_true_fails") { return Err("invalid failure_semantics literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct WaraRuleBinding {
    pub aprl_guid: String,
    pub query_digest: String,
    pub rule_id: String,
    pub rule_version: String,
    pub rule_digest: String,
    pub capability: Box<WaraRuleCapability>,
    pub reviewer: String,
    pub review_state: String,
}

impl WaraRuleBinding {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.review_state.as_str(), "reviewed-exact") { return Err("invalid review_state literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct WaraRuleBindingCatalog {
    pub schema_version: String,
    pub source_revision: String,
    pub crosswalk_digest: String,
    pub bindings: Vec<WaraRuleBinding>,
    pub overlay_digest: String,
}

impl WaraRuleBindingCatalog {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.schema_version.as_str(), "1.0.0") { return Err("invalid schema_version literal"); }
        Ok(())
    }
}

pub const SHA256: &str = "^sha256:[a-f0-9]{64}$";
pub const UUID: &str = "^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$";
pub const GIT_REF: &str = "^[a-f0-9]{40}$";
pub const IDENTIFIER: &str = "^[a-z0-9][a-z0-9._:-]{0,255}$";
pub const SEMVER: &str = "^[0-9]+\\.[0-9]+\\.[0-9]+$";
impl WaraRuleCapability {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn ordered(&self) -> Result<WaraRuleCapability, &'static str> {
        Err("runtime_binding_required")
    }
}

impl WaraRuleBinding {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn evaluator_ref(&self) -> String {
        format!("t0-rule-evaluator:{}@{}", self.rule_id.clone(), self.rule_version.clone())
    }
}

impl WaraRuleBindingCatalog {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn identity(&self) -> Result<WaraRuleBindingCatalog, &'static str> {
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn resolve(&self, mut aprl_guid: String, mut query_digest: String) -> Option<WaraRuleBinding> {
        if aprl_guid.is_empty() {
            return None;
        }
        None
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn load_wara_rule_bindings(mut path: String, mut catalog: String, mut queries: String, mut rules: Vec<String>, mut rule_digest: String) -> Result<WaraRuleBindingCatalog, &'static str> {
    if path.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

pub const PUBLIC_EXPORTS: &[&str] = &["WaraRuleBinding", "WaraRuleBindingCatalog", "WaraRuleCapability", "load_wara_rule_bindings"];
