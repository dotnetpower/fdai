#[derive(Clone, Debug, Default, PartialEq)]
pub struct SregymPlugin {
    pub plugin_id: String,
    pub api_version: String,
}

impl SregymPlugin {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn create_adapter(&self) -> Result<String, &'static str> {
        Err("runtime_binding_required")
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn create_plugin() -> SregymPlugin {
    SregymPlugin::default()
}

pub const PUBLIC_EXPORTS: &[&str] = &["SregymPlugin", "create_plugin"];
