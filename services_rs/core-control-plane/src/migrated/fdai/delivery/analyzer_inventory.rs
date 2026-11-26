#[derive(Clone, Debug, Default, PartialEq)]
pub struct AnalyzerInventorySources {
    pub projection: String,
    pub provider_references: String,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct AnalyzerInventoryIdentityError {
    pub message: String,
}

impl AnalyzerInventoryIdentityError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for AnalyzerInventoryIdentityError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for AnalyzerInventoryIdentityError {}

pub trait AnalyzerProviderReferenceReader {
    fn read_active_resources(&self, resource_ids: Vec<String>) -> String;
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn build_analyzer_inventory_sources(mut dsn: String) -> Option<AnalyzerInventorySources> {
    Some(AnalyzerInventorySources::default())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub async fn read_provider_query_references(mut reader: Option<String>, mut expected_resource_types: std::collections::BTreeMap<String, String>, mut expected_snapshot_id: Option<String>) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    let Some(mut reader) = reader.clone() else { return Err("active inventory provider identity reader is unavailable"); };
    let mut provider_query_refs: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::<String, String>::new();
    Ok(provider_query_refs.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub async fn read_resources_by_provider_references(mut reader: Option<String>, mut provider_refs: Vec<String>, mut expected_snapshot_id: Option<String>) -> Result<(Option<String>, std::collections::BTreeMap<String, String>), &'static str> {
    if (provider_refs.clone()).is_empty() {
        return Ok((None, std::collections::BTreeMap::<String, String>::new()));
    }
    let Some(mut reader) = reader.clone() else { return Err("configured provider references require an active inventory reader"); };
    Ok((None, std::collections::BTreeMap::new()))
}

pub const PUBLIC_EXPORTS: &[&str] = &["AnalyzerInventoryIdentityError", "AnalyzerInventorySources", "AnalyzerProviderReferenceReader", "build_analyzer_inventory_sources", "read_provider_query_references", "read_resources_by_provider_references"];
