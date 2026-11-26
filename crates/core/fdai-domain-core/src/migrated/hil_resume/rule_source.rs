#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn resolve_parked_rule(mut parked: std::collections::BTreeMap<String, String>, mut action: String, mut rules_by_id: std::collections::BTreeMap<String, String>) -> Option<String> {
    let rule_id: String = ((parked.clone()).get("rule_id").cloned()).unwrap_or_else(|| String::from(""));
    let catalog_rule: Option<String> = (rules_by_id.clone()).get(rule_id.as_str()).cloned();
    if let Some(mut catalog_rule) = catalog_rule.clone() {
        return Some(catalog_rule.clone());
    }
    None
}

pub const PUBLIC_EXPORTS: &[&str] = &["resolve_parked_rule"];
