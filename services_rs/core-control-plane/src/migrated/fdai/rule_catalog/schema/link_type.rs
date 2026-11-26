#[derive(Clone, Debug, Default, PartialEq)]
pub struct LinkTypeIssue {
    pub key: String,
    pub message: String,
}

pub const LINK_TYPE_SCHEMA_NAME: &str = "ontology/link-type";
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct LinkTypeCatalogError {
    pub message: String,
}

impl LinkTypeCatalogError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for LinkTypeCatalogError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for LinkTypeCatalogError {}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn yaml_load(mut path: String) -> String {
    if path.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
#[allow(clippy::type_complexity)]
pub fn cross_reference_issues(mut link: String, mut origin: String, mut object_type_names: std::collections::BTreeSet<String>, mut object_types_by_name: Option<std::collections::BTreeMap<String, String>>) -> Vec<LinkTypeIssue> {
    let mut issues: Vec<LinkTypeIssue> = Vec::<LinkTypeIssue>::new();
    issues.clone()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn load_link_type_from_mapping(mut raw: std::collections::BTreeMap<String, String>, mut schema_registry: String, mut object_type_names: std::collections::BTreeSet<String>, mut object_types_by_name: Option<std::collections::BTreeMap<String, String>>, mut origin: String) -> Result<String, &'static str> {
    let mut issues: Vec<LinkTypeIssue> = Vec::<LinkTypeIssue>::new();
    if !(issues.clone()).is_empty() {
        return Err("issues");
    }
    let xref_issues: Vec<LinkTypeIssue> = cross_reference_issues(String::new(), origin.clone(), object_type_names.clone(), object_types_by_name.clone());
    if !(xref_issues.clone()).is_empty() {
        return Err("xref_issues");
    }
    Ok(String::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn iter_yaml_files(mut root: String) -> Vec<String> {
    if root.is_empty() {
        return Vec::new();
    }
    Vec::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn load_link_type_catalog(mut root: String, mut schema_registry: String, mut object_types: Vec<String>) -> Result<Vec<String>, &'static str> {
    let mut aggregated: Vec<LinkTypeIssue> = Vec::<LinkTypeIssue>::new();
    let mut loaded: Vec<String> = Vec::<String>::new();
    let mut seen_names: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::<String, String>::new();
    for path in iter_yaml_files(root.clone()) {
        let raw: String = yaml_load(path.clone());
        if !(false) {
            aggregated.push(LinkTypeIssue { message: String::from("top-level must be a mapping"), ..Default::default() });
            continue;
        }
        let model: String = load_link_type_from_mapping(std::collections::BTreeMap::new(), schema_registry.clone(), std::collections::BTreeSet::new(), None, String::new()).unwrap_or_else(|_| String::new());
        loaded.push(model.clone());
    }
    if !(aggregated.clone()).is_empty() {
        return Err("aggregated");
    }
    Ok(loaded.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn link_type_names(mut catalog: Vec<String>) -> std::collections::BTreeSet<String> {
    std::collections::BTreeSet::new()
}

pub const PUBLIC_EXPORTS: &[&str] = &["LinkTypeCatalogError", "LinkTypeIssue", "link_type_names", "load_link_type_catalog", "load_link_type_from_mapping"];
