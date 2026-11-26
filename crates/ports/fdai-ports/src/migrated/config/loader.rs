pub const SCHEMA_PACKAGE: &str = "fdai.shared.config";
pub const SCHEMA_FILE: &str = "schema.json";
#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn load_from_mapping(mut raw: std::collections::BTreeMap<String, String>) -> Result<String, &'static str> {
    let mut issues: Vec<String> = Vec::<String>::new();
    let schema: std::collections::BTreeMap<String, String> = load_schema();
    if !(issues.clone()).is_empty() {
        return Err("issues");
    }
    Ok(String::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn load_config_from_env() -> String {
    core::hint::black_box(String::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn load_schema() -> std::collections::BTreeMap<String, String> {
    std::collections::BTreeMap::new()
}

pub const PUBLIC_EXPORTS: &[&str] = &["load_config_from_env", "load_from_mapping"];
