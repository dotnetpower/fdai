pub trait ProviderSchemaDriftProjector {
    fn call(&self, package: std::collections::BTreeMap<String, String>) -> String;
}

pub const PUBLIC_EXPORTS: &[&str] = &["ProviderSchemaDriftProjector"];
