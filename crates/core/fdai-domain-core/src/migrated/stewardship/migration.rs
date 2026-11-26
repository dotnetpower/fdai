#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct StewardshipMigrationError {
    pub message: String,
}

impl StewardshipMigrationError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for StewardshipMigrationError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for StewardshipMigrationError {}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn migrate_stewardship_mapping_to_v2(mut raw: std::collections::BTreeMap<String, String>) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    let mut missing_backup: Vec<String> = Vec::<String>::new();
    if !(missing_backup.clone()).is_empty() {
        return Err("stewardship v2 migration requires a second accountable subject for:    .");
    }
    Ok(std::collections::BTreeMap::new())
}

pub const PUBLIC_EXPORTS: &[&str] = &["StewardshipMigrationError", "migrate_stewardship_mapping_to_v2"];
