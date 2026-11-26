#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct TelemetryRecipeNodeHandler {
    pub initialized: bool,
}

impl TelemetryRecipeNodeHandler {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn call(&self, mut node: String, mut dependencies: std::collections::BTreeMap<String, String>) -> Result<String, &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["TELEMETRY_RECIPE_ARGUMENT_SCHEMA", "TelemetryRecipeNodeHandler"];
