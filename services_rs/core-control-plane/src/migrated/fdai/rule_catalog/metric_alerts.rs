pub const MAX_DESCRIPTION_LENGTH: i64 = 512;
pub const MAX_METRIC_ALERT_ENTRIES: i64 = 256;

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum MetricAlertComparison {
    #[default]
    Above,
    AtOrAbove,
    Below,
    AtOrBelow,
}

impl MetricAlertComparison {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Above => "above",
            Self::AtOrAbove => "at_or_above",
            Self::Below => "below",
            Self::AtOrBelow => "at_or_below",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct MetricAlertEntry {
    pub schema_version: String,
    pub alert_id: String,
    pub description: String,
    pub metric: String,
    pub resource_type: Option<String>,
    pub comparison: MetricAlertComparison,
    pub threshold: f64,
    pub window: String,
    pub frequency: String,
    pub severity: i64,
    pub mode: String,
    pub provenance: String,
}

impl MetricAlertEntry {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.schema_version.as_str(), "1.0.0") { return Err("invalid schema_version literal"); }
        if !(0_i64..=4_i64).contains(&self.severity) { return Err("severity out of bounds"); }
        if !matches!(self.mode.as_str(), "shadow") { return Err("invalid mode literal"); }
        Ok(())
    }
}

pub const ALERT_ID_PATTERN: &str = "^[a-z][a-z0-9.-]{2,95}$";
pub const METRIC_PATTERN: &str = "^[a-z][a-z0-9._-]{0,127}$";
pub const ARM_TYPE_PATTERN: &str = "^[A-Z][A-Za-z0-9.]{1,63}/[A-Za-z][A-Za-z0-9/]{1,127}$";
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct MetricAlertCatalogError {
    pub message: String,
}

impl MetricAlertCatalogError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for MetricAlertCatalogError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for MetricAlertCatalogError {}

impl MetricAlertEntry {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn require_supported_evaluation(&self) -> Result<MetricAlertEntry, &'static str> {
        Err("runtime_binding_required")
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn load_metric_alert_catalog(mut directory: String) -> Result<Vec<MetricAlertEntry>, &'static str> {
    let mut entries: std::collections::BTreeMap<String, MetricAlertEntry> = std::collections::BTreeMap::<String, MetricAlertEntry>::new();
    Ok(Vec::new())
}

pub const PUBLIC_EXPORTS: &[&str] = &["FREQUENCY_MINUTES", "MAX_METRIC_ALERT_ENTRIES", "WINDOW_MINUTES", "MetricAlertCatalogError", "MetricAlertComparison", "MetricAlertEntry", "load_metric_alert_catalog"];
