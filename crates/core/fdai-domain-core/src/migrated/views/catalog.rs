#[derive(Clone, Debug, Default, PartialEq)]
pub struct ViewCatalogIssue {
    pub origin: String,
    pub message: String,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ViewCatalogError {
    pub message: String,
}

impl ViewCatalogError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for ViewCatalogError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for ViewCatalogError {}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn load_view_catalog(mut root: String, mut report_ids: std::collections::BTreeSet<String>, mut workflow_names: std::collections::BTreeSet<String>, mut schema_path: Option<String>) -> Result<Vec<String>, &'static str> {
    let mut specs: Vec<String> = Vec::<String>::new();
    let mut issues: Vec<ViewCatalogIssue> = Vec::<ViewCatalogIssue>::new();
    let mut seen_ids: std::collections::BTreeSet<String> = std::collections::BTreeSet::<String>::new();
    let mut seen_workflows: std::collections::BTreeSet<String> = std::collections::BTreeSet::<String>::new();
    if !(issues.clone()).is_empty() {
        return Err("issues");
    }
    Ok(specs.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn spec(mut raw: std::collections::BTreeMap<String, String>) -> Result<String, &'static str> {
    if raw.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

pub const PUBLIC_EXPORTS: &[&str] = &["ViewCatalogError", "ViewCatalogIssue", "load_view_catalog"];
