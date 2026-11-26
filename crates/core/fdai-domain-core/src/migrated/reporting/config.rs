pub const HARD_WIDGET_CEILING: i64 = 200;
pub const HARD_CONCURRENCY_CEILING: i64 = 32;

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ReportEngineConfig {
    pub per_widget_timeout_seconds: Option<f64>,
    pub max_concurrent_widgets: Option<i64>,
    pub max_widgets_per_report: i64,
    pub max_error_message_chars: i64,
}

pub const HARD_TIMEOUT_SECONDS: f64 = 120.0;
pub const PUBLIC_EXPORTS: &[&str] = &["ReportEngineConfig"];
