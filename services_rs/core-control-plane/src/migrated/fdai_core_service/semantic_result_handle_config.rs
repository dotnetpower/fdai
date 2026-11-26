pub const RESULT_HANDLES_ENV: &str = "FDAI_SEMANTIC_RESULT_HANDLES";
pub const RESULT_HANDLE_MATERIAL_ENV: &str = "FDAI_RESULT_HANDLE_MATERIAL";
#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn result_handle_store_from_config(mut config: std::collections::BTreeMap<String, String>, mut enabled: Option<bool>) -> Option<String> {
    let Some(mut enabled) = enabled.clone() else { return None; };
    let dsn: String = ((config.clone()).get("FDAI_STATE_STORE_DSN").cloned().unwrap_or_else(|| String::from(""))).trim().to_string();
    if ((dsn.clone()).is_empty()) || ((((config.clone()).get(RESULT_HANDLE_MATERIAL_ENV).cloned().unwrap_or_else(|| String::from(""))).trim().to_string()).is_empty()) {
        return None;
    }
    None
}

pub const PUBLIC_EXPORTS: &[&str] = &["RESULT_HANDLES_ENV", "RESULT_HANDLE_MATERIAL_ENV", "result_handle_store_from_config"];
