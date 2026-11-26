#[derive(Clone, Debug, Default, PartialEq)]
pub struct PostgresAzureResourceIdentityResolverConfig {
    pub dsn: String,
    pub freshness_budget_seconds: i64,
    pub statement_timeout_ms: i64,
    pub connect_timeout_s: i64,
}

impl PostgresAzureResourceIdentityResolverConfig {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.dsn.trim().is_empty() { return Err("dsn must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct PostgresAzureResourceIdentityResolver {
    pub initialized: bool,
}

impl PostgresAzureResourceIdentityResolver {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn resolve(&self, mut resource_ref: String, mut at: Option<String>) -> Result<Option<String>, &'static str> {
        if (resource_ref.trim().to_string()).is_empty() {
            return Err("neutral resource ref MUST be non-empty");
        }
        Ok(None)
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["PostgresAzureResourceIdentityResolver", "PostgresAzureResourceIdentityResolverConfig"];
