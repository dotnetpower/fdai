#[derive(Clone, Debug, Default, PartialEq)]
pub struct InvestigationStrategyComparisonEvidence {
    pub comparison_id: String,
    pub comparison_digest: String,
    pub active_strategy_digest: String,
    pub challenger_strategy_digest: String,
    pub disposition: String,
    pub challenger_outcome: Option<String>,
    pub agreement: bool,
    pub realized_evidence_eligible: bool,
    pub safety_failure: bool,
    pub invariant_failure: bool,
    pub comparison_material_json: String,
    pub execution_authority: bool,
    pub promotion_authority: bool,
}

impl InvestigationStrategyComparisonEvidence {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.execution_authority { return Err("execution_authority violated literal bool invariant"); }
        if self.promotion_authority { return Err("promotion_authority violated literal bool invariant"); }
        Ok(())
    }
}

impl InvestigationStrategyComparisonEvidence {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn from_shadow(mut comparison: String) -> InvestigationStrategyComparisonEvidence {
        if comparison.is_empty() {
            return Default::default();
        }
        Default::default()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn from_mapping(mut value: std::collections::BTreeMap<String, String>) -> Result<InvestigationStrategyComparisonEvidence, &'static str> {
        let allowed: std::collections::BTreeSet<String> = std::collections::BTreeSet::from([String::from("comparison_id"), String::from("comparison_digest"), String::from("active_strategy_digest"), String::from("challenger_strategy_digest"), String::from("disposition"), String::from("challenger_outcome"), String::from("agreement"), String::from("realized_evidence_eligible"), String::from("safety_failure"), String::from("invariant_failure"), String::from("comparison_material_json"), String::from("execution_authority"), String::from("promotion_authority")]);
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn to_mapping(&self) -> std::collections::BTreeMap<String, String> {
        std::collections::BTreeMap::from([(String::from("comparison_id"), self.comparison_id.clone()), (String::from("comparison_digest"), self.comparison_digest.clone()), (String::from("active_strategy_digest"), self.active_strategy_digest.clone()), (String::from("challenger_strategy_digest"), self.challenger_strategy_digest.clone()), (String::from("disposition"), String::new()), (String::from("challenger_outcome"), String::new()), (String::from("agreement"), String::new()), (String::from("realized_evidence_eligible"), String::new()), (String::from("safety_failure"), String::new()), (String::from("invariant_failure"), String::new()), (String::from("comparison_material_json"), self.comparison_material_json.clone()), (String::from("execution_authority"), String::new()), (String::from("promotion_authority"), String::new())])
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn text(mut name: String, mut value: String) -> Result<(), &'static str> {
    if ((value.clone()).is_empty()) || ((((value.clone()).len() as i64)) > (256_i64)) {
        return Err("name MUST be non-empty and bounded");
    }
    Ok(())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn digest(mut name: String, mut value: String) -> Result<(), &'static str> {
    if name.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn boolean(mut value: String, mut name: String) -> Result<bool, &'static str> {
    if !(false) {
        return Err("name MUST be boolean");
    }
    Ok(false)
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn r#false(mut value: String, mut name: String) -> Result<bool, &'static str> {
    Ok(false)
}

pub const PUBLIC_EXPORTS: &[&str] = &["InvestigationStrategyComparisonEvidence"];
