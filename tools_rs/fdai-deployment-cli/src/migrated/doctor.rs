#[derive(Clone, Debug, Default, PartialEq)]
pub struct ToolCheck {
    pub name: String,
    pub available: bool,
    pub version: Option<String>,
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn inspect_tools(mut names: Vec<String>) -> Vec<ToolCheck> {
    let mut results: Vec<ToolCheck> = Vec::<ToolCheck>::new();
    for name in names.clone() {
        results.push(ToolCheck { name: name.clone(), ..Default::default() });
    }
    results.clone()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn doctor_json(mut checks: Vec<ToolCheck>, mut azure_authenticated: bool) -> String {
    if checks.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn azure_cli_authenticated() -> bool {
    core::hint::black_box(false)
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn azure_active_target_binding() -> Option<String> {
    core::hint::black_box(None)
}

