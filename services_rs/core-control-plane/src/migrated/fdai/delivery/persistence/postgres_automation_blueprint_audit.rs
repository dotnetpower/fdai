#[derive(Clone, Debug, Default, PartialEq)]
pub struct PostgresAutomationBlueprintAuditConfig {
    pub dsn: String,
    pub statement_timeout_ms: i64,
    pub connect_timeout_s: i64,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct PostgresAutomationBlueprintAudit {
    pub initialized: bool,
}

impl PostgresAutomationBlueprintAudit {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn append(&self, mut event: std::collections::BTreeMap<String, String>) {
        let payload: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("kind"), String::from("automation_blueprint.audit")), (String::from("recorded_at"), String::new()), (String::from("event"), String::new()), (String::from("execution_authority"), String::new())]);
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["PostgresAutomationBlueprintAudit", "PostgresAutomationBlueprintAuditConfig"];
