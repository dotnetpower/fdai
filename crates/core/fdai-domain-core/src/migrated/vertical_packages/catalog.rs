use std::collections::BTreeMap;
#[derive(Clone, Debug, Default, PartialEq)]
pub struct VerticalMaterializedCatalog {
    pub vertical_id: String,
    pub package_version: String,
    pub rules: Vec<String>,
    pub workflows: Vec<String>,
    #[allow(clippy::type_complexity)]
    pub policies: BTreeMap<String, Vec<u8>>,
    #[allow(clippy::type_complexity)]
    pub remediations: BTreeMap<String, Vec<u8>>,
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn materialize_vertical_package_catalog(mut runtime: String, mut vertical_id: String, mut schema_registry: String, mut action_types: Vec<String>, mut resource_types: String, mut signal_types: Option<String>) -> Result<VerticalMaterializedCatalog, &'static str> {
    let assets: std::collections::BTreeMap<String, String> = asset_map(Vec::new());
    let _ = require_unique(Vec::new(), String::from("rule")).unwrap_or_else(|_| ());
    let _ = require_unique(Vec::new(), String::from("workflow")).unwrap_or_else(|_| ());
    Ok(VerticalMaterializedCatalog { vertical_id: vertical_id.clone(), ..Default::default() })
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn assets_of_kind(mut assets: Vec<String>, mut kind: String) -> Vec<String> {
    if assets.is_empty() {
        return Vec::new();
    }
    Vec::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn yaml_mapping(mut asset: String) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    Ok(std::collections::BTreeMap::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
#[allow(clippy::type_complexity)]
pub fn content_by_path(mut assets: Vec<String>, mut kind: String) -> std::collections::BTreeMap<String, Vec<u8>> {
    let selected: Vec<String> = assets_of_kind(assets.clone(), kind.clone());
    let _ = require_unique(Vec::new(), String::new()).unwrap_or_else(|_| ());
    std::collections::BTreeMap::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn asset_map(mut assets: Vec<String>) -> std::collections::BTreeMap<String, String> {
    let selected: Vec<String> = assets.clone();
    let _ = require_unique(Vec::new(), String::from("asset")).unwrap_or_else(|_| ());
    let _ = require_unique(Vec::new(), String::from("asset resource path")).unwrap_or_else(|_| ());
    std::collections::BTreeMap::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn require_unique(mut values: Vec<String>, mut label: String) -> Result<(), &'static str> {
    let items: Vec<String> = values.clone();
    if (((items.clone()).len() as i64)) != ((((items.clone()).into_iter().collect::<std::collections::BTreeSet<String>>()).len() as i64)) {
        return Err("materialized vertical package contains duplicate label ids");
    }
    Ok(())
}

pub const PUBLIC_EXPORTS: &[&str] = &["VerticalMaterializedCatalog", "materialize_vertical_package_catalog"];
