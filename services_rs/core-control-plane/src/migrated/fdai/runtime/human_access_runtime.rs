#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn build_human_access_workflow(mut r#loop: String, mut store: String, mut environment: std::collections::BTreeMap<String, String>, mut http_client: Option<String>, mut identity: Option<String>, mut enforce_ready: String, mut clock: String) -> Result<Option<String>, &'static str> {
    let raw: String = ((environment.clone()).get("FDAI_HUMAN_ACCESS_ROLE_GROUPS_JSON").cloned().unwrap_or_else(|| String::from(""))).trim().to_string();
    let read_principal: String = (((environment.clone()).get("FDAI_MI_CLIENT_ID").cloned().unwrap_or_else(|| String::from(""))).trim().to_string()).to_lowercase();
    let mutation_principal: String = (((environment.clone()).get("FDAI_HUMAN_ACCESS_MI_CLIENT_ID").cloned().unwrap_or_else(|| String::from(""))).trim().to_string()).to_lowercase();
    if (!(read_principal.clone()).is_empty()) && ((read_principal.clone()) == (mutation_principal.clone())) {
        return Err("Core read identity MUST NOT share isolated human-access mutation identit");
    }
    if (read_principal.clone()).is_empty() {
        return Ok(None);
    }
    Ok(None)
}

pub const PUBLIC_EXPORTS: &[&str] = &["build_human_access_workflow"];
