#[derive(Clone, Debug, Default, PartialEq)]
pub struct PostgresTrustedArtifactStoreConfig {
    pub dsn: String,
    pub statement_timeout_ms: i64,
    pub connect_timeout_s: i64,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct PostgresTrustedArtifactStore {
    pub initialized: bool,
}

impl PostgresTrustedArtifactStore {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn put(&self, mut record: String, mut expected_revision: i64) -> Result<String, &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn values(mut record: String) -> Vec<String> {
    if record.is_empty() {
        return Vec::new();
    }
    Vec::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn row_to_record(mut row: std::collections::BTreeMap<String, String>) -> String {
    if row.is_empty() {
        return String::new();
    }
    String::new()
}

pub const PUBLIC_EXPORTS: &[&str] = &["PostgresTrustedArtifactStore", "PostgresTrustedArtifactStoreConfig"];
