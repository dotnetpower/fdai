#[derive(Clone, Debug, Default, PartialEq)]
pub struct RetentionStatement {
    pub delete_sql: String,
    pub readback_sql: String,
    pub params: Vec<String>,
}

pub const RESULT_PREDICATE: &str = "FROM briefing_run WHERE principal_id = %s AND run_id = %s";
pub const ANCHOR_PREDICATE: &str = "FROM scheduled_conversation_anchor WHERE anchor_id = %s";
pub trait SubmittedDeliveryRetentionDeleter {
    fn call(&self, anchor: String) -> String;
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct RetentionReadbackError {
    pub message: String,
}

impl RetentionReadbackError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for RetentionReadbackError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for RetentionReadbackError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct PostgresScheduledContinuationDeleter {
    pub initialized: bool,
}

impl PostgresScheduledContinuationDeleter {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn delete(&self, mut target: String, mut anchor: String) -> Result<(), &'static str> {
        let statement: RetentionStatement = retention_statement(target.clone(), anchor.clone()).unwrap_or_else(|_| Default::default());
        Ok(())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn connect(&self) -> String {
        if !self.initialized {
            return String::new();
        }
        String::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn timeout(&self, mut connection: String) {
        if !self.initialized {
            return;
        }
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn retention_statement(mut target: String, mut anchor: String) -> Result<RetentionStatement, &'static str> {
    if target.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

pub const PUBLIC_EXPORTS: &[&str] = &["PostgresScheduledContinuationDeleter", "RetentionReadbackError", "RetentionStatement", "retention_statement"];
