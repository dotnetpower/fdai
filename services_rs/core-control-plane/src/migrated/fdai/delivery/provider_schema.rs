#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ProviderSchemaChannel {
    #[default]
    Stable,
    Preview,
}

impl ProviderSchemaChannel {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Stable => "stable",
            Self::Preview => "preview",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ProviderSchemaCoverageStatus {
    #[default]
    Modeled,
    StructuralOnly,
    ReadOnly,
    PreviewOnly,
    UnsupportedWithReason,
}

impl ProviderSchemaCoverageStatus {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Modeled => "modeled",
            Self::StructuralOnly => "structural-only",
            Self::ReadOnly => "read-only",
            Self::PreviewOnly => "preview-only",
            Self::UnsupportedWithReason => "unsupported-with-reason",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ProviderSchemaDriftKind {
    #[default]
    Unchanged,
    Compatible,
    Breaking,
}

impl ProviderSchemaDriftKind {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Unchanged => "unchanged",
            Self::Compatible => "compatible",
            Self::Breaking => "breaking",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ProviderSchemaType {
    pub resource_type: String,
    pub stable_api_versions: Vec<String>,
    pub preview_api_versions: Vec<String>,
    pub preferred_api_version: String,
    pub source_document: String,
    pub parent_type: Option<String>,
    pub readable_scopes: Vec<String>,
    pub writable_scopes: Vec<String>,
    pub scope_evidence_available: bool,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ProviderSchemaSnapshot {
    pub provider: String,
    pub source_revision: String,
    pub types: Vec<ProviderSchemaType>,
    pub schema_digest: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ProviderSchemaCoverageEntry {
    pub resource_type: String,
    pub status: ProviderSchemaCoverageStatus,
    pub reason: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ProviderSchemaCoverage {
    pub schema_digest: String,
    pub entries: Vec<ProviderSchemaCoverageEntry>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ProviderSchemaDrift {
    pub baseline_digest: String,
    pub observed_digest: String,
    pub kind: ProviderSchemaDriftKind,
    pub added_types: Vec<String>,
    pub removed_types: Vec<String>,
    pub added_stable_versions: Vec<String>,
    pub removed_stable_versions: Vec<String>,
    pub added_preview_versions: Vec<String>,
    pub removed_preview_versions: Vec<String>,
    pub drift_digest: String,
}

pub const TYPE_PATTERN: &str = "^[A-Za-z][A-Za-z0-9.]+/[A-Za-z0-9][A-Za-z0-9./-]*$";
pub const DIGEST_PATTERN: &str = "^sha256:[0-9a-f]{64}$";
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ProviderSchemaError {
    pub message: String,
}

impl ProviderSchemaError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for ProviderSchemaError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for ProviderSchemaError {}

impl ProviderSchemaType {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn preferred_channel(&self) -> ProviderSchemaChannel {
        core::hint::black_box(Default::default())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn to_mapping(&self) -> std::collections::BTreeMap<String, String> {
        std::collections::BTreeMap::from([(String::from("resource_type"), self.resource_type.clone()), (String::from("stable_api_versions"), String::new()), (String::from("preview_api_versions"), String::new()), (String::from("preferred_api_version"), self.preferred_api_version.clone()), (String::from("preferred_channel"), String::new()), (String::from("source_document"), self.source_document.clone()), (String::from("parent_type"), (self.parent_type.clone()).unwrap_or_default()), (String::from("readable_scopes"), String::new()), (String::from("writable_scopes"), String::new()), (String::from("scope_evidence_available"), String::new())])
    }
}

impl ProviderSchemaSnapshot {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn build(mut provider: String, mut source_revision: String, mut types: Vec<ProviderSchemaType>) -> Result<ProviderSchemaSnapshot, &'static str> {
        let normalized_provider: String = (provider.trim().to_string()).to_lowercase();
        if ((normalized_provider.clone()).is_empty()) || (((source_revision.clone()).trim().to_string()).is_empty()) {
            return Err("provider and immutable source_revision MUST be non-empty");
        }
        let payload: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("schema_version"), String::from("1.0.0")), (String::from("provider"), normalized_provider.clone()), (String::from("source_revision"), (source_revision.clone()).trim().to_string()), (String::from("types"), String::new())]);
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn to_mapping(&self) -> std::collections::BTreeMap<String, String> {
        std::collections::BTreeMap::from([(String::from("schema_version"), String::from("1.0.0")), (String::from("provider"), self.provider.clone()), (String::from("source_revision"), self.source_revision.clone()), (String::from("schema_digest"), self.schema_digest.clone()), (String::from("type_count"), String::new()), (String::from("types"), String::new()), (String::from("grants_authority"), String::new())])
    }
}

impl ProviderSchemaCoverage {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn build(mut snapshot: ProviderSchemaSnapshot, mut modeled_provider_types: std::collections::BTreeSet<String>) -> ProviderSchemaCoverage {
        let mut entries: Vec<ProviderSchemaCoverageEntry> = Vec::<ProviderSchemaCoverageEntry>::new();
        for item in snapshot.types.clone() {
            entries.push(ProviderSchemaCoverageEntry { resource_type: item.resource_type.clone(), ..Default::default() });
        }
        Default::default()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn modeled_count(&self) -> i64 {
        0_i64
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn to_mapping(&self) -> std::collections::BTreeMap<String, String> {
        let mut status_counts: std::collections::BTreeMap<String, i64> = std::collections::BTreeMap::<String, i64>::new();
        std::collections::BTreeMap::from([(String::from("schema_version"), String::from("1.0.0")), (String::from("schema_digest"), self.schema_digest.clone()), (String::from("type_count"), String::new()), (String::from("modeled_count"), String::new()), (String::from("status_counts"), String::new()), (String::from("entries"), String::new()), (String::from("grants_authority"), String::new())])
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn compare_provider_schema_snapshots(mut baseline: ProviderSchemaSnapshot, mut observed: ProviderSchemaSnapshot) -> Result<ProviderSchemaDrift, &'static str> {
    if (baseline.provider.clone()) != (observed.provider.clone()) {
        return Err("provider schema snapshots MUST have the same provider");
    }
    let material: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("schema_version"), String::from("1.0.0")), (String::from("provider"), baseline.provider.clone()), (String::from("baseline_digest"), baseline.schema_digest.clone()), (String::from("observed_digest"), observed.schema_digest.clone()), (String::from("kind"), String::new()), (String::from("added_types"), String::new()), (String::from("removed_types"), String::new()), (String::from("added_stable_versions"), String::new()), (String::from("removed_stable_versions"), String::new()), (String::from("added_preview_versions"), String::new()), (String::from("removed_preview_versions"), String::new())]);
    Ok(ProviderSchemaDrift { baseline_digest: baseline.schema_digest.clone(), observed_digest: observed.schema_digest.clone(), ..Default::default() })
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn provider_schema_snapshot_from_mapping(mut raw: std::collections::BTreeMap<String, String>) -> Result<ProviderSchemaSnapshot, &'static str> {
    if ((raw.clone()).get("schema_version").cloned()) != Some(String::from("1.0.0")) {
        return Err("provider schema snapshot version is unsupported");
    }
    let provider: Option<String> = (raw.clone()).get("provider").cloned();
    let source_revision: Option<String> = (raw.clone()).get("source_revision").cloned();
    let raw_types: Option<String> = (raw.clone()).get("types").cloned();
    if (!(true)) || (!(true)) {
        return Err("provider schema snapshot identity is invalid");
    }
    if (!(true)) || (true) {
        return Err("provider schema snapshot types MUST be an array");
    }
    let mut types: Vec<ProviderSchemaType> = Vec::<ProviderSchemaType>::new();
    let expected_digest: Option<String> = (raw.clone()).get("schema_digest").cloned();
    let type_count: Option<String> = (raw.clone()).get("type_count").cloned();
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn provider_schema_observation_time(mut value: String) -> Result<String, &'static str> {
    if value.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn normalized_values(mut values: Vec<String>, mut field: String) -> Result<Vec<String>, &'static str> {
    if values.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn casefold_optional(mut value: Option<String>) -> Option<String> {
    if value.is_none() { None } else { Some(((value.clone()).unwrap_or_default()).to_lowercase()) }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn canonical_json(mut value: String) -> Vec<u8> {
    if value.is_empty() {
        return Vec::new();
    }
    Vec::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn is_string_sequence(mut value: String) -> bool {
    if value.is_empty() {
        return false;
    }
    false
}

pub const PUBLIC_EXPORTS: &[&str] = &["ProviderSchemaChannel", "ProviderSchemaCoverage", "ProviderSchemaCoverageEntry", "ProviderSchemaCoverageStatus", "ProviderSchemaDrift", "ProviderSchemaDriftKind", "ProviderSchemaError", "ProviderSchemaSnapshot", "ProviderSchemaType", "compare_provider_schema_snapshots", "provider_schema_observation_time", "provider_schema_snapshot_from_mapping"];
