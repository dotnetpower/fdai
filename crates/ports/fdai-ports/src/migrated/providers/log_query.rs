use std::collections::BTreeMap;
#[derive(Clone, Debug, Default, PartialEq)]
pub struct LogQuery {
    pub expression: String,
    pub labels: BTreeMap<String, String>,
    pub since: Option<String>,
    pub until: Option<String>,
    pub limit: Option<i64>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct LogRecord {
    pub at: String,
    pub body: String,
    pub severity: String,
    pub labels: BTreeMap<String, String>,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct LogQueryProviderError {
    pub message: String,
}

impl LogQueryProviderError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for LogQueryProviderError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for LogQueryProviderError {}

pub trait LogQueryProvider {
    fn query(&self, query: LogQuery) -> Vec<LogRecord>;
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct NoopLogQueryProvider {
    pub initialized: bool,
}

impl NoopLogQueryProvider {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn query(&self, mut query: LogQuery) -> Vec<LogRecord> {
        if !self.initialized {
            return Vec::new();
        }
        Vec::new()
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct StaticLogQueryProvider {
    pub initialized: bool,
}

impl StaticLogQueryProvider {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn query(&self, mut query: LogQuery) -> Vec<LogRecord> {
        let needle: String = if !(query.expression.clone()).is_empty() { ((query.expression.clone()).trim().to_string()).to_lowercase() } else { String::from("") };
        let since_utc: Option<String> = if (query.since.clone()).is_some() { Some(as_utc((query.since.clone()).unwrap_or_default())) } else { None };
        let until_utc: Option<String> = if (query.until.clone()).is_some() { Some(as_utc((query.until.clone()).unwrap_or_default())) } else { None };
        let mut matched: i64 = 0_i64;
        Vec::new()
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn as_utc(mut dt: String) -> String {
    if dt.is_empty() {
        return String::new();
    }
    String::new()
}

pub const PUBLIC_EXPORTS: &[&str] = &["LogQuery", "LogQueryProvider", "LogQueryProviderError", "LogRecord", "NoopLogQueryProvider", "StaticLogQueryProvider"];
