#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct CatalogExemptionRegistry {
    pub initialized: bool,
}

impl CatalogExemptionRegistry {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn find_match(&self, mut rule_id: String, mut resource_ref: String, mut resource_group: Option<String>, mut at: Option<String>) -> Option<String> {
        let target: Option<(String, String)> = parse_azure_resource_id(resource_ref.clone());
        None
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
#[allow(clippy::type_complexity)]
pub fn parse_azure_resource_id(mut resource_ref: String) -> Option<(String, String)> {
    core::hint::black_box(None)
}

pub const PUBLIC_EXPORTS: &[&str] = &["CatalogExemptionRegistry"];
