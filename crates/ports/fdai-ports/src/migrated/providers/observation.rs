use std::collections::BTreeMap;
#[derive(Clone, Debug, Default, PartialEq)]
pub struct LogQueryResult {
    #[allow(clippy::type_complexity)]
    pub rows: Vec<BTreeMap<String, String>>,
    pub truncated: bool,
    pub scanned_records: Option<i64>,
    pub metadata: BTreeMap<String, String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct MetricPoint {
    pub timestamp: String,
    pub value: f64,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct MetricQueryResult {
    pub namespace: String,
    pub metric: String,
    pub aggregation: String,
    pub points: Vec<MetricPoint>,
    pub metadata: BTreeMap<String, String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct DeploymentRecord {
    pub deployment_ref: String,
    pub timestamp: String,
    pub author: String,
    pub resource_refs: Vec<String>,
    pub status: String,
    pub metadata: BTreeMap<String, String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct DeploymentHistoryResult {
    pub records: Vec<DeploymentRecord>,
    pub window: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct IncidentCorrelation {
    pub incident_id: String,
    #[allow(clippy::type_complexity)]
    pub events: Vec<BTreeMap<String, String>>,
    #[allow(clippy::type_complexity)]
    pub audit_entries: Vec<BTreeMap<String, String>>,
    #[allow(clippy::type_complexity)]
    pub log_hits: Vec<BTreeMap<String, String>>,
    pub metric_points: Vec<MetricPoint>,
    pub deployments: Vec<DeploymentRecord>,
    pub metadata: BTreeMap<String, String>,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ObservationError {
    pub message: String,
}

impl ObservationError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for ObservationError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for ObservationError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct LogQueryError {
    pub message: String,
}

impl LogQueryError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for LogQueryError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for LogQueryError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct MetricQueryError {
    pub message: String,
}

impl MetricQueryError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for MetricQueryError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for MetricQueryError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct DeploymentHistoryError {
    pub message: String,
}

impl DeploymentHistoryError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for DeploymentHistoryError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for DeploymentHistoryError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct IncidentCorrelationError {
    pub message: String,
}

impl IncidentCorrelationError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for IncidentCorrelationError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for IncidentCorrelationError {}

pub trait LogQueryProvider {
    fn query_log(&self, query: String, window: String, max_rows: i64) -> LogQueryResult;
}

pub trait MetricQueryProvider {
    fn query_metric(&self, namespace: String, metric: String, aggregation: String, window: String) -> MetricQueryResult;
}

pub trait DeploymentHistoryProvider {
    fn query_deployments(&self, window: String, resource_ref: Option<String>) -> DeploymentHistoryResult;
}

pub trait CutoffDeploymentHistoryProvider {
    fn query_deployments_until(&self, window: String, resource_ref: Option<String>, until: String) -> String;
}

pub trait IncidentCorrelator {
    fn correlate(&self, incident_id: String) -> IncidentCorrelation;
}

pub const PUBLIC_EXPORTS: &[&str] = &["DeploymentHistoryError", "DeploymentHistoryProvider", "CutoffDeploymentHistoryProvider", "DeploymentHistoryResult", "DeploymentRecord", "IncidentCorrelation", "IncidentCorrelationError", "IncidentCorrelator", "LogQueryError", "LogQueryProvider", "LogQueryResult", "MetricPoint", "MetricQueryError", "MetricQueryProvider", "MetricQueryResult", "ObservationError"];
