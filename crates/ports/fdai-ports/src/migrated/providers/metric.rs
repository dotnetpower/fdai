use std::collections::BTreeMap;
#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum MetricFailureReason {
    #[default]
    Unknown,
    Timeout,
    TransportError,
    HttpError,
    InvalidResponse,
    ResponseLimit,
    InvalidQuery,
    ProviderError,
}

impl MetricFailureReason {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Unknown => "unknown",
            Self::Timeout => "timeout",
            Self::TransportError => "transport_error",
            Self::HttpError => "http_error",
            Self::InvalidResponse => "invalid_response",
            Self::ResponseLimit => "response_limit",
            Self::InvalidQuery => "invalid_query",
            Self::ProviderError => "provider_error",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct MetricQuery {
    pub metric_name: String,
    pub labels: BTreeMap<String, String>,
    pub since: Option<String>,
    pub until: Option<String>,
    pub aggregation: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct MetricPoint {
    pub metric_name: String,
    pub at: String,
    pub value: f64,
    pub labels: BTreeMap<String, String>,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct MetricProviderError {
    pub message: String,
}

impl MetricProviderError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for MetricProviderError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for MetricProviderError {}

pub trait MetricProvider {
    fn query(&self, query: MetricQuery) -> Vec<MetricPoint>;
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct NoopMetricProvider {
    pub initialized: bool,
}

impl NoopMetricProvider {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn query(&self, mut query: MetricQuery) -> Vec<MetricPoint> {
        if !self.initialized {
            return Vec::new();
        }
        Vec::new()
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct StaticMetricProvider {
    pub initialized: bool,
}

impl StaticMetricProvider {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn query(&self, mut query: MetricQuery) -> Vec<MetricPoint> {
        if !self.initialized {
            return Vec::new();
        }
        Vec::new()
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn labels_match(mut sample_labels: std::collections::BTreeMap<String, String>, mut query_labels: std::collections::BTreeMap<String, String>) -> bool {
    if sample_labels.is_empty() {
        return false;
    }
    false
}

pub const PUBLIC_EXPORTS: &[&str] = &["MetricFailureReason", "MetricPoint", "MetricProvider", "MetricProviderError", "MetricQuery", "NoopMetricProvider", "StaticMetricProvider"];
