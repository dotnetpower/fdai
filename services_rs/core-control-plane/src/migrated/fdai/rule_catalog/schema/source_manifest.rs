#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum FetchKind {
    #[default]
    Git,
    Http,
    Local,
}

impl FetchKind {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Git => "git",
            Self::Http => "http",
            Self::Local => "local",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum Redistribution {
    #[default]
    Embeddable,
    ReferenceOnly,
}

impl Redistribution {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Embeddable => "embeddable",
            Self::ReferenceOnly => "reference-only",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum Cadence {
    #[default]
    OnDemand,
    Daily,
    Weekly,
    Monthly,
}

impl Cadence {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::OnDemand => "on-demand",
            Self::Daily => "daily",
            Self::Weekly => "weekly",
            Self::Monthly => "monthly",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ManifestIssue {
    pub key: String,
    pub message: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct FetchConfig {
    pub kind: FetchKind,
    pub repo: Option<String>,
    pub revision: Option<String>,
    pub subpath: Option<String>,
    pub url: Option<String>,
    pub expected_sha256: Option<String>,
    pub path: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct SourceManifest {
    pub schema_version: String,
    pub id: String,
    pub name: String,
    pub url_prefix: Option<String>,
    pub license: String,
    pub redistribution: Redistribution,
    pub fetch: Box<FetchConfig>,
    pub parser: String,
    pub cadence: Cadence,
}

pub const SCHEMA_PACKAGE: &str = "fdai.rule_catalog.schema";
pub const SCHEMA_FILE: &str = "source_manifest.schema.json";
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ManifestError {
    pub message: String,
}

impl ManifestError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for ManifestError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for ManifestError {}

impl FetchConfig {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn require_per_kind_fields(&self) -> Result<FetchConfig, &'static str> {
        Err("runtime_binding_required")
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn load_json_schema() -> std::collections::BTreeMap<String, String> {
    std::collections::BTreeMap::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn load_source_manifest_from_mapping(mut raw: std::collections::BTreeMap<String, String>) -> Result<SourceManifest, &'static str> {
    let mut issues: Vec<ManifestIssue> = Vec::<ManifestIssue>::new();
    let schema: std::collections::BTreeMap<String, String> = load_json_schema();
    if !(issues.clone()).is_empty() {
        return Err("issues");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn load_source_manifest_from_yaml(mut path: String) -> Result<SourceManifest, &'static str> {
    Ok(load_source_manifest_from_mapping(std::collections::BTreeMap::new()).unwrap_or_else(|_| Default::default()))
}

pub const PUBLIC_EXPORTS: &[&str] = &["Cadence", "FetchConfig", "FetchKind", "ManifestError", "ManifestIssue", "Redistribution", "SourceManifest", "load_source_manifest_from_mapping", "load_source_manifest_from_yaml"];
