pub const WARA_FRAMEWORK_ID: &str = "azure-wara";
#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn load_release_wara_rule_bindings(mut repo_root: String, mut catalog: String, mut queries: String) -> String {
    if repo_root.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub async fn with_wara_rule_evidence(mut request: String, mut state_store: String, mut activation: Option<String>, mut scope: String, mut catalog: String, mut bindings: String) -> (String, String) {
    (String::new(), String::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn release_rules(mut repo_root: String) -> Result<Vec<String>, &'static str> {
    if repo_root.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

pub const PUBLIC_EXPORTS: &[&str] = &["WARA_FRAMEWORK_ID", "load_release_wara_rule_bindings", "with_wara_rule_evidence"];
