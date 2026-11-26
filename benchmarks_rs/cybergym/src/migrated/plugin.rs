#[derive(Clone, Debug, Default, PartialEq)]
pub struct CyberGymPlugin {
    pub plugin_id: String,
    pub api_version: String,
}

pub const MANIFEST_ENV: &str = "CYBERGYM_TASK_MANIFEST";
impl CyberGymPlugin {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn create_adapter(&self) -> Result<String, &'static str> {
        Err("runtime_binding_required")
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn task_config(mut payload: std::collections::BTreeMap<String, String>) -> Result<String, &'static str> {
    if payload.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn artifact(mut value: String) -> Option<String> {
    if value.is_empty() {
        return None;
    }
    None
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn create_plugin() -> CyberGymPlugin {
    CyberGymPlugin::default()
}

pub const PUBLIC_EXPORTS: &[&str] = &["CyberGymPlugin", "create_plugin"];
