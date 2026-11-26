pub const SCHEMA_PACKAGE: &str = "fdai.rule_catalog.schema";
pub const SCHEMA_FILE: &str = "signal_types.schema.json";
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct SignalTypeRegistryError {
    pub message: String,
}

impl SignalTypeRegistryError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for SignalTypeRegistryError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for SignalTypeRegistryError {}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn load_signal_type_registry_from_mapping(mut raw: std::collections::BTreeMap<String, String>) -> Result<String, &'static str> {
    if raw.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

pub const PUBLIC_EXPORTS: &[&str] = &["SignalDispatchMode", "SignalTypeEntry", "SignalTypeRegistry", "SignalTypeRegistryError", "load_signal_type_registry_from_mapping"];
