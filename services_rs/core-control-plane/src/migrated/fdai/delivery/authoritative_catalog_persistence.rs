pub trait CatalogConnection {
    fn execute(&self, query: String, params: String) -> String;
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub async fn write_catalog_snapshots_atomic(mut dsn: String, mut snapshots: std::collections::BTreeMap<String, std::collections::BTreeMap<String, String>>, mut statement_timeout_ms: i64, mut connect_timeout_s: i64) -> Result<(), &'static str> {
    if (dsn.clone()).is_empty() {
        return Err("catalog snapshot DSN MUST NOT be empty");
    }
    if ((statement_timeout_ms) < (1_i64)) || ((connect_timeout_s) < (1_i64)) {
        return Err("catalog snapshot timeouts MUST be positive");
    }
    Ok(())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub async fn write_catalog_snapshots_in_transaction(mut connection: String, mut snapshots: std::collections::BTreeMap<String, std::collections::BTreeMap<String, String>>, mut statement_timeout_ms: i64) -> Result<(), &'static str> {
    if (statement_timeout_ms) < (1_i64) {
        return Err("statement_timeout_ms MUST be positive");
    }
    Ok(())
}

pub const PUBLIC_EXPORTS: &[&str] = &["write_catalog_snapshots_atomic", "write_catalog_snapshots_in_transaction"];
