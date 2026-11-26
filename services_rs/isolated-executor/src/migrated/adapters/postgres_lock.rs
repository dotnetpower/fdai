#[derive(Clone, Debug, Default, PartialEq)]
pub struct PostgresAdvisoryResourceLockConfig {
    pub dsn: String,
    pub lock_timeout_ms: i64,
    pub connect_timeout_s: i64,
}

pub const LOCK_SQL: &str = "SELECT pg_advisory_lock(hashtextextended(%s, 0))";
pub const UNLOCK_SQL: &str = "SELECT pg_advisory_unlock(hashtextextended(%s, 0))";
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct PostgresAdvisoryResourceLock {
    pub initialized: bool,
}

impl PostgresAdvisoryResourceLock {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn acquire(&self, mut resource_id: String) -> Vec<()> {
        if !self.initialized {
            return Vec::new();
        }
        Vec::new()
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn resource_digest(mut resource_id: String) -> String {
    if resource_id.is_empty() {
        return String::new();
    }
    String::new()
}

pub const PUBLIC_EXPORTS: &[&str] = &["PostgresAdvisoryResourceLock", "PostgresAdvisoryResourceLockConfig"];
