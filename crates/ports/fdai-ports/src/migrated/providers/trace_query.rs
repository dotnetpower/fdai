use std::collections::BTreeMap;
#[derive(Clone, Debug, Default, PartialEq)]
pub struct TraceQuery {
    pub trace_id: Option<String>,
    pub service: Option<String>,
    pub operation: Option<String>,
    pub labels: BTreeMap<String, String>,
    pub since: Option<String>,
    pub until: Option<String>,
    pub min_duration: Option<String>,
    pub limit: Option<i64>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Span {
    pub trace_id: String,
    pub span_id: String,
    pub parent_span_id: Option<String>,
    pub service: String,
    pub operation: String,
    pub start: String,
    pub duration: String,
    pub status: String,
    pub labels: BTreeMap<String, String>,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct TraceQueryProviderError {
    pub message: String,
}

impl TraceQueryProviderError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for TraceQueryProviderError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for TraceQueryProviderError {}

pub trait TraceQueryProvider {
    fn query(&self, query: TraceQuery) -> Vec<Span>;
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct NoopTraceQueryProvider {
    pub initialized: bool,
}

impl NoopTraceQueryProvider {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn query(&self, mut query: TraceQuery) -> Vec<Span> {
        if !self.initialized {
            return Vec::new();
        }
        Vec::new()
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct StaticTraceQueryProvider {
    pub initialized: bool,
}

impl StaticTraceQueryProvider {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn query(&self, mut query: TraceQuery) -> Vec<Span> {
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

pub const PUBLIC_EXPORTS: &[&str] = &["NoopTraceQueryProvider", "Span", "StaticTraceQueryProvider", "TraceQuery", "TraceQueryProvider", "TraceQueryProviderError"];
