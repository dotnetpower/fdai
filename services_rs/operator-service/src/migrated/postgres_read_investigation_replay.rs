#[derive(Clone, Debug, Default, PartialEq)]
pub struct PostgresReadInvestigationReplayConfig {
    pub dsn: String,
    pub statement_timeout_ms: i64,
    pub connect_timeout_s: i64,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct PostgresReadInvestigationReplayStore {
    pub initialized: bool,
}

impl PostgresReadInvestigationReplayStore {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn replay(&self, mut query: String) -> Result<String, &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn fetch_all(&self, mut statement: String, mut parameters: std::collections::BTreeMap<String, String>) -> Result<Vec<std::collections::BTreeMap<String, String>>, &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn object(mut value: String) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    Ok(std::collections::BTreeMap::new())
}

pub const PUBLIC_EXPORTS: &[&str] = &["PostgresReadInvestigationReplayConfig", "PostgresReadInvestigationReplayStore"];
