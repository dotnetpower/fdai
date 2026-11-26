use std::collections::BTreeMap;
pub const MAX_FILE_BYTES: i64 = 1048576;

#[derive(Clone, Debug, Default, PartialEq)]
pub struct LocalCurationEvidence {
    pub revision: i64,
    pub digest: String,
    pub accepted_sha256: String,
    pub source_revision: i64,
    pub key_digest: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ReleaseCatalog {
    pub releases: BTreeMap<String, String>,
    #[allow(clippy::type_complexity)]
    pub channels: BTreeMap<String, Vec<String>>,
    pub recalls: Vec<String>,
    #[allow(clippy::type_complexity)]
    pub local_curation: Option<Box<LocalCurationEvidence>>,
    #[allow(clippy::type_complexity)]
    pub plan_types: Option<Vec<String>>,
}

impl ReleaseCatalog {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    #[allow(clippy::type_complexity)]
    pub fn newer_than(&self, mut channel: String, mut release_id: Option<String>) -> Vec<(String, String)> {
        if channel.is_empty() {
            return Vec::new();
        }
        Vec::new()
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn load_catalog(mut root: String) -> ReleaseCatalog {
    ReleaseCatalog::default()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn read(mut path: String) -> Result<Vec<u8>, &'static str> {
    if path.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

