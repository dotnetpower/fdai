#[derive(Clone, Debug, Default, PartialEq)]
pub struct HeimdallProviderSchemaMixin {
    pub bus: Option<String>,
}

impl HeimdallProviderSchemaMixin {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn publish_provider_schema_drift(&self, mut package: std::collections::BTreeMap<String, String>) -> bool {
        if self.bus.is_none() {
            return false;
        }
        true
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["HeimdallProviderSchemaMixin"];
