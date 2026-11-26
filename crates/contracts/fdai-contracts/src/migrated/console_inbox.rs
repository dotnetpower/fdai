#[derive(Clone, Debug, Default, PartialEq)]
pub struct ConsoleInboxRecord {
    pub schema_version: String,
    pub inbox_id: String,
    pub category: String,
    pub trust_tier: String,
    pub severity: String,
    pub title: String,
    pub body: String,
    pub correlation_id: String,
    pub audit_id: Option<String>,
    pub recorded_at: String,
    pub execution_authority: bool,
}

impl ConsoleInboxRecord {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.schema_version.as_str(), "1.0.0") { return Err("invalid schema_version literal"); }
        if !matches!(self.trust_tier.as_str(), "a2_operational_alert") { return Err("invalid trust_tier literal"); }
        if !matches!(self.severity.as_str(), "info" | "warn" | "error" | "critical") { return Err("invalid severity literal"); }
        if self.execution_authority { return Err("execution_authority violated literal bool invariant"); }
        Ok(())
    }
}

pub const CONSOLE_INBOX_PREFIX: &str = "console-inbox:";
pub const PUBLIC_EXPORTS: &[&str] = &["CONSOLE_INBOX_PREFIX", "ConsoleInboxRecord", "InboxSeverity"];
