use std::collections::BTreeMap;
#[derive(Clone, Debug, Default, PartialEq)]
pub struct ProbeIssue {
    pub key: String,
    pub message: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ProbeManifest {
    pub id: String,
    pub description: String,
    pub adapter_ref: String,
    pub adapter_payload: BTreeMap<String, String>,
    pub interpretation: BTreeMap<String, String>,
    pub timeout_seconds: i64,
    pub cache_ttl_seconds: i64,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ProbeCatalogError {
    pub message: String,
}

impl ProbeCatalogError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for ProbeCatalogError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for ProbeCatalogError {}

impl ProbeManifest {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn from_mapping(mut raw: std::collections::BTreeMap<String, String>) -> ProbeManifest {
        if raw.is_empty() {
            return Default::default();
        }
        Default::default()
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn iter_probe_files(mut root: String) -> Vec<String> {
    if root.is_empty() {
        return Vec::new();
    }
    Vec::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn load_schema(mut schema_path: String) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    Ok(std::collections::BTreeMap::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn load_probe_catalog(mut root: String) -> Result<Vec<ProbeManifest>, &'static str> {
    let schema: std::collections::BTreeMap<String, String> = load_schema(String::new()).unwrap_or_else(|_| std::collections::BTreeMap::new());
    let mut issues: Vec<ProbeIssue> = Vec::<ProbeIssue>::new();
    let mut loaded: Vec<ProbeManifest> = Vec::<ProbeManifest>::new();
    let mut seen_ids: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::<String, String>::new();
    if !(issues.clone()).is_empty() {
        return Err("issues");
    }
    Ok(loaded.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn probe_ids(mut catalog: Vec<ProbeManifest>) -> std::collections::BTreeSet<String> {
    std::collections::BTreeSet::new()
}

pub const PUBLIC_EXPORTS: &[&str] = &["ProbeCatalogError", "ProbeIssue", "ProbeManifest", "load_probe_catalog", "probe_ids"];
