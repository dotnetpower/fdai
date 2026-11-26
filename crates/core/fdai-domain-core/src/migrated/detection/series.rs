#[derive(Clone, Debug, Default, PartialEq)]
pub struct MetricSample {
    pub timestamp: String,
    pub value: f64,
}

pub const PUBLIC_EXPORTS: &[&str] = &["MetricSample"];
