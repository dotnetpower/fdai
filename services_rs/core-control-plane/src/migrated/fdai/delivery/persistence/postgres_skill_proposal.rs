#[derive(Clone, Debug, Default, PartialEq)]
pub struct PostgresSkillProposalStoreConfig {
    pub dsn: String,
    pub statement_timeout_ms: i64,
    pub connect_timeout_s: i64,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct PostgresSkillProposalStore {
    pub initialized: bool,
}

impl PostgresSkillProposalStore {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn create(&self, mut proposal: String) -> String {
        if !self.initialized {
            return String::new();
        }
        String::new()
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn row_to_proposal(mut row: std::collections::BTreeMap<String, String>) -> String {
    if row.is_empty() {
        return String::new();
    }
    String::new()
}

pub const PUBLIC_EXPORTS: &[&str] = &["PostgresSkillProposalStore", "PostgresSkillProposalStoreConfig"];
