#[derive(Clone, Debug, Default, PartialEq)]
pub struct ProviderRegion {
    pub id: String,
    pub display_name: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ProviderRegionRegistry {
    pub schema_version: String,
    pub version: String,
    pub provider: String,
    pub regions: Vec<ProviderRegion>,
}

impl ProviderRegionRegistry {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.schema_version.as_str(), "1.0.0") { return Err("invalid schema_version literal"); }
        Ok(())
    }
}

pub const REGION_ID: &str = "^[a-z][a-z0-9]{1,63}$";
impl ProviderRegionRegistry {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn sorted_unique(&self) -> Result<ProviderRegionRegistry, &'static str> {
        Err("runtime_binding_required")
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn load_provider_region_registry_from_mapping(mut raw: std::collections::BTreeMap<String, String>) -> ProviderRegionRegistry {
    if raw.is_empty() {
        return Default::default();
    }
    Default::default()
}

pub const PUBLIC_EXPORTS: &[&str] = &["ProviderRegion", "ProviderRegionRegistry", "load_provider_region_registry_from_mapping"];
