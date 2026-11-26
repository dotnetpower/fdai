#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum Aggregation {
    #[default]
    Max,
    Min,
    Avg,
    Sum,
    Last,
    P50,
    P95,
    P99,
}

impl Aggregation {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Max => "max",
            Self::Min => "min",
            Self::Avg => "avg",
            Self::Sum => "sum",
            Self::Last => "last",
            Self::P50 => "p50",
            Self::P95 => "p95",
            Self::P99 => "p99",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum Comparison {
    #[default]
    Gte,
    Lte,
}

impl Comparison {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Gte => "gte",
            Self::Lte => "lte",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Threshold {
    pub metric: String,
    pub compare: Comparison,
    pub bound: f64,
    pub severity: String,
    pub signal: String,
    pub observation: String,
    pub aggregation: Aggregation,
    pub remediation_ref: Option<String>,
}

impl Threshold {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.metric.trim().is_empty() { return Err("metric must be non-empty"); }
        if self.severity.trim().is_empty() { return Err("severity must be non-empty"); }
        if self.signal.trim().is_empty() { return Err("signal must be non-empty"); }
        if self.observation.trim().is_empty() { return Err("observation must be non-empty"); }
        Ok(())
    }
}

pub const DEFAULT_LABEL_KEY: &str = "resource_id";
pub trait ResourceAnalyzer {
    fn resource_kind(&self) -> String;
    fn analyze(&self, resource_ref: String, window_seconds: f64) -> Vec<String>;
}

impl Threshold {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn breached(&self, mut value: f64) -> bool {
        (value) <= (self.bound)
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ThresholdAnalyzer {
    pub initialized: bool,
}

impl ThresholdAnalyzer {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn resource_kind(&self) -> String {
        if !self.initialized {
            return String::new();
        }
        String::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn analyze(&self, mut resource_ref: String, mut window_seconds: f64) -> Result<Vec<String>, &'static str> {
        let mut findings: Vec<String> = Vec::<String>::new();
        Ok(findings.clone())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn gather(&self, mut metric: String, mut resource_ref: String, mut since: String, mut until: String, mut aggregation: Aggregation) -> Vec<String> {
        if !self.initialized {
            return Vec::new();
        }
        Vec::new()
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn reduce_values(mut values: Vec<f64>, mut how: Aggregation) -> Result<Option<f64>, &'static str> {
    if (values.clone()).is_empty() {
        return Ok(None);
    }
    Ok(None)
}

pub const PUBLIC_EXPORTS: &[&str] = &["Aggregation", "Comparison", "MetricProvider", "ResourceAnalyzer", "Threshold", "ThresholdAnalyzer", "reduce_values"];
