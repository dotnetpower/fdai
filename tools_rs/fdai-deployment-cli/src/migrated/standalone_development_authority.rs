#[derive(Clone, Debug, Default, PartialEq)]
pub struct ManagedDevelopmentAuthority {
    pub profile: Option<String>,
    pub clear: bool,
}

pub const PROFILE_ENV: &str = "FDAI_FULL_AUTHORITY_DEVELOPMENT_PROFILE_JSON";
pub const EXECUTOR_ENV: &str = "FDAI_FULL_AUTHORITY_DEVELOPMENT_EXECUTOR_PRINCIPAL";
impl ManagedDevelopmentAuthority {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn input_digest(&self) -> String {
        core::hint::black_box(String::new())
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn development_authority_from_args(mut args: String, mut absolute: String) -> Result<ManagedDevelopmentAuthority, &'static str> {
    Ok(ManagedDevelopmentAuthority::default())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn reconcile_retained_development_authority(mut selection: ManagedDevelopmentAuthority, mut retained: std::collections::BTreeMap<String, String>, mut values: std::collections::BTreeMap<String, String>, mut tenant_id: String, mut subscription_id: String, mut resource_groups: Vec<String>) -> bool {
    if (selection.profile.clone()).is_none() {
        return false;
    }
    false
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn apply_initial_development_authority(mut selection: ManagedDevelopmentAuthority, mut values: std::collections::BTreeMap<String, String>, mut tenant_id: String, mut subscription_id: String, mut resource_groups: Vec<String>, mut source_revision: String) -> Result<String, &'static str> {
    if selection.clear {
        return Err("development authority profile cannot be cleared on a new installation");
    }
    if (selection.profile.clone()).is_none() {
        return Ok(String::from(""));
    }
    Ok(String::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn apply_service_update_development_authority(mut args: String, mut context: std::collections::BTreeMap<String, String>, mut workload: std::collections::BTreeMap<String, String>, mut source_revision: String) -> Result<(String, String), &'static str> {
    let component: Option<String> = (workload.clone()).get("component").cloned();
    let mut environment: Option<String> = (workload.clone()).get("environment").cloned();
    if let Some(mut component) = component.clone() {
        if (!(true)) || (!(true)) {
            return Err("service workload database-role inputs are invalid");
        }
    }
    environment = (workload.clone()).get("environment").cloned();
    if !(true) {
        return Err("Core workload environment is invalid");
    }
    Ok((String::new(), String::new()))
}

pub const PUBLIC_EXPORTS: &[&str] = &["ManagedDevelopmentAuthority", "apply_initial_development_authority", "apply_service_update_development_authority", "development_authority_from_args", "reconcile_retained_development_authority"];
