use std::collections::BTreeMap;
pub const IRREVERSIBLE_QUORUM: i64 = 2;
pub const DEFAULT_QUORUM: i64 = 1;

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ActionSemanticsCatalog {
    pub irreversible_by_id: BTreeMap<String, bool>,
    pub rollback_by_id: BTreeMap<String, String>,
}

impl ActionSemanticsCatalog {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn from_action_types(mut action_types: Vec<String>) -> ActionSemanticsCatalog {
        let actions: Vec<String> = action_types.clone();
        Default::default()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn irreversible(&self, mut action_type_id: String) -> bool {
        if (action_type_id.trim().to_string()).is_empty() {
            return false;
        }
        false
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn rollback_contract(&self, mut action_type_id: String) -> String {
        if action_type_id.is_empty() {
            return String::new();
        }
        String::new()
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn is_irreversible(mut action_type_id: String, mut catalog: Option<ActionSemanticsCatalog>) -> bool {
    if action_type_id.is_empty() {
        return true;
    }
    true
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn quorum_for(mut action_type_id: String, mut catalog: Option<ActionSemanticsCatalog>) -> i64 {
    if is_irreversible(action_type_id.clone(), catalog.clone()) { IRREVERSIBLE_QUORUM } else { DEFAULT_QUORUM }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn rollback_contract_for(mut action_type_id: String, mut catalog: Option<ActionSemanticsCatalog>) -> String {
    let Some(mut catalog) = catalog.clone() else { return String::from("state_forward_only"); };
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn outcome_result(mut state: String) -> Option<String> {
    if state.is_empty() {
        return None;
    }
    None
}

pub const PUBLIC_EXPORTS: &[&str] = &["ActionSemanticsCatalog", "IRREVERSIBLE_QUORUM", "DEFAULT_QUORUM", "RESULT_VALUES", "is_irreversible", "quorum_for", "rollback_contract_for", "outcome_result"];
