#[derive(Clone, Debug, Default, PartialEq)]
pub struct ActionStopCondition {
    pub kind: String,
    pub threshold: Option<f64>,
    pub window_seconds: Option<i64>,
    pub seconds: Option<i64>,
    pub count: Option<i64>,
}

pub const PUBLIC_EXPORTS: &[&str] = &["ActionStopCondition"];
