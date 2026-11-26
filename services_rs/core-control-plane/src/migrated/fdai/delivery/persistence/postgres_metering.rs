pub const DEFAULT_MAX_RECORDS: i64 = 50000;

#[derive(Clone, Debug, Default, PartialEq)]
pub struct PostgresMeteringStoreConfig {
    pub dsn: String,
    pub statement_timeout_ms: i64,
    pub connect_timeout_s: i64,
    pub max_records: i64,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct PostgresMeteringStore {
    pub initialized: bool,
}

impl PostgresMeteringStore {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn record(&self, mut invocation: String) {
        if !self.initialized {
            return;
        }
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn invocations(&self) -> Vec<String> {
        if !self.initialized {
            return Vec::new();
        }
        Vec::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn connect(&self, mut row_factory: bool) -> String {
        let mut kwargs: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("connect_timeout"), String::new())]);
        String::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn set_statement_timeout(&self, mut connection: String) {
        if !self.initialized {
            return;
        }
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn row_to_invocation(mut row: std::collections::BTreeMap<String, String>) -> String {
    if row.is_empty() {
        return String::new();
    }
    String::new()
}

pub const PUBLIC_EXPORTS: &[&str] = &["PostgresMeteringStore", "PostgresMeteringStoreConfig"];
