#[derive(Clone, Debug, Default, PartialEq)]
pub struct PostgresCostGovernanceConfig {
    pub dsn: String,
    pub statement_timeout_ms: i64,
    pub connect_timeout_s: i64,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct PostgresCostGovernanceReader {
    pub initialized: bool,
}

impl PostgresCostGovernanceReader {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn read_access(&self, mut principal_id: String, mut purpose: String, mut scope: String, mut now: String) -> String {
        if !self.initialized {
            return String::new();
        }
        String::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn read_activation(&self, mut package_id: String) -> Option<String> {
        if !self.initialized {
            return None;
        }
        None
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn read_analytics(&self, mut scope: String) -> Option<String> {
        if !self.initialized {
            return None;
        }
        None
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn psycopg_dsn(mut value: String) -> String {
    if value.is_empty() {
        return String::new();
    }
    String::new()
}

pub const PUBLIC_EXPORTS: &[&str] = &["PostgresCostGovernanceConfig", "PostgresCostGovernanceReader", "UnavailableCostGovernanceReader"];
