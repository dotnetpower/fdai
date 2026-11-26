pub const DIGEST: &str = "sha256:[0-9a-f]{64}";
pub const IDENTIFIER: &str = "[a-z0-9][a-z0-9._:-]{0,127}";
pub const SEMVER: &str = "\\d+\\.\\d+\\.\\d+";
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct DevelopmentProfileTfvarsError {
    pub message: String,
}

impl DevelopmentProfileTfvarsError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for DevelopmentProfileTfvarsError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for DevelopmentProfileTfvarsError {}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn selected_profile_json(mut raw_json: Option<String>) -> String {
    if raw_json.is_none() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn bind_development_profile(mut materialized: std::collections::BTreeMap<String, String>, mut service: String, mut environment: String, mut raw_json: Option<String>, mut approval_profile_json: Option<String>) -> Result<(), &'static str> {
    let selected: String = selected_profile_json(raw_json.clone());
    if (selected.clone()).is_empty() {
        return Ok(());
    }
    if let Some(mut approval_profile_json) = approval_profile_json.clone() {
        return Err("production and development approval profiles are mutually exclusive");
    }
    if ((service.clone()) != (String::from("core-control-plane"))) || ((environment.clone()) != (String::from("dev"))) {
        return Err("full-authority development profile is valid only for Core in dev");
    }
    let profile: std::collections::BTreeMap<String, String> = profile(String::new()).unwrap_or_else(|_| std::collections::BTreeMap::new());
    Ok(())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn profile(mut value: String) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    let _ = identifier(String::new(), String::from("profile_id")).unwrap_or_else(|_| String::new());
    let owner: String = text(String::new(), String::from("owner_principal")).unwrap_or_else(|_| String::new());
    let executor: String = text(String::new(), String::from("executor_principal")).unwrap_or_else(|_| String::new());
    if (((owner.clone()).trim().to_string()).to_lowercase()) == (((executor.clone()).trim().to_string()).to_lowercase()) {
        return Err("development Owner and executor principals MUST be distinct");
    }
    let valid_from: String = aware_time(String::new(), String::from("valid_from")).unwrap_or_else(|_| String::new());
    let valid_until: String = aware_time(String::new(), String::from("valid_until")).unwrap_or_else(|_| String::new());
    if (valid_from.clone()) >= (valid_until.clone()) {
        return Err("development authority interval is invalid");
    }
    let _ = scope(String::new()).unwrap_or_else(|_| ());
    let _ = revision(String::new(), String::from("source_revision")).unwrap_or_else(|_| ());
    let _ = revision(String::new(), String::from("catalog_revision")).unwrap_or_else(|_| ());
    let _ = revision(String::new(), String::from("policy_revision")).unwrap_or_else(|_| ());
    let _ = actions(String::new()).unwrap_or_else(|_| ());
    Ok(std::collections::BTreeMap::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn scope(mut value: String) -> Result<(), &'static str> {
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn actions(mut value: String) -> Result<(), &'static str> {
    if (!(false)) || ((value.clone()).is_empty()) {
        return Err("development authority registered actions are required");
    }
    let mut identities: Vec<(String, String, String)> = Vec::<(String, String, String)>::new();
    Ok(())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn digest(mut value: String, mut name: String) -> Result<String, &'static str> {
    Ok(value.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn identifier(mut value: String, mut name: String) -> Result<String, &'static str> {
    Ok(value.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn text(mut value: String, mut name: String) -> Result<String, &'static str> {
    if (!(true)) || (((value.trim().to_string()).is_empty()) || ((((value.clone()).len() as i64)) > (256_i64))) {
        return Err("development authority name is invalid");
    }
    Ok(value.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn revision(mut value: String, mut name: String) -> Result<(), &'static str> {
    if (!(true)) || (!(((1_i64) <= (((value.clone()).len() as i64))) && ((((value.clone()).len() as i64)) <= (256_i64)))) {
        return Err("development authority name is invalid");
    }
    Ok(())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn aware_time(mut value: String, mut name: String) -> Result<String, &'static str> {
    if !(true) {
        return Err("development authority name is invalid");
    }
    Ok(String::new())
}

pub const PUBLIC_EXPORTS: &[&str] = &["DevelopmentProfileTfvarsError", "bind_development_profile", "selected_profile_json"];
