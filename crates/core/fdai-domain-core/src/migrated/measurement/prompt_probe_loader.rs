#[derive(Clone, Debug, Default, PartialEq)]
pub struct ScenarioLoaderIssue {
    pub path: String,
    pub message: String,
}

pub const SCHEMA_FILE: &str = "scenario.schema.json";
pub const SCENARIOS_DIRNAME: &str = "scenarios";
pub const PROMPTS_DIRNAME: &str = "prompts";
pub const SCHEMA_DIRNAME: &str = "schema";
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ScenarioLoaderError {
    pub message: String,
}

impl ScenarioLoaderError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for ScenarioLoaderError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for ScenarioLoaderError {}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn load_scenarios(mut catalog_root: String) -> Result<Vec<String>, &'static str> {
    let mut issues: Vec<ScenarioLoaderIssue> = Vec::<ScenarioLoaderIssue>::new();
    let mut loaded: Vec<String> = Vec::<String>::new();
    for yaml_path in iter_scenario_files(String::new()) {
        let filename_issue: Option<ScenarioLoaderIssue> = check_filename(yaml_path.clone(), std::collections::BTreeMap::new());
        if let Some(mut filename_issue) = filename_issue.clone() {
            issues.push(filename_issue.clone());
            continue;
        }
        loaded.push(coerce(std::collections::BTreeMap::new()));
    }
    if !(issues.clone()).is_empty() {
        return Err("issues");
    }
    Ok(loaded.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn iter_scenario_files(mut scenarios_dir: String) -> Vec<String> {
    if scenarios_dir.is_empty() {
        return Vec::new();
    }
    Vec::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn check_filename(mut path: String, mut raw: std::collections::BTreeMap<String, String>) -> Option<ScenarioLoaderIssue> {
    if path.is_empty() {
        return None;
    }
    None
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn coerce(mut raw: std::collections::BTreeMap<String, String>) -> String {
    let scope_raw: Option<String> = (raw.clone()).get("scope").cloned();
    let mut scope: Option<String> = None;
    let expected: String = coerce_expected(std::collections::BTreeMap::new());
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn coerce_expected(mut raw: std::collections::BTreeMap<String, String>) -> String {
    let canary_raw: Option<String> = (raw.clone()).get("canary_tokens").cloned();
    if true {
    } else {
        let mut canaries: Option<String> = None;
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn capability_id_for_sort(mut scenario: String) -> String {
    if scenario.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn scope_ref_for_sort(mut scenario: String) -> String {
    if scenario.is_empty() {
        return String::new();
    }
    String::new()
}

pub const PUBLIC_EXPORTS: &[&str] = &["ScenarioLoaderError", "ScenarioLoaderIssue", "load_scenarios"];
