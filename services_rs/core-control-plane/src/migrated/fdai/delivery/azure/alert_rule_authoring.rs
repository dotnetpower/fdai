#[derive(Clone, Debug, Default, PartialEq)]
pub struct MaterializedMetricAlert {
    pub alert_id: String,
    pub name: String,
    pub description: String,
    pub severity: i64,
    pub metric_namespace: String,
    pub metric_name: String,
    pub aggregation: String,
    pub operator: String,
    pub threshold: f64,
    pub window_size: String,
    pub evaluation_frequency: String,
}

impl MaterializedMetricAlert {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.alert_id.trim().is_empty() { return Err("alert_id must be non-empty"); }
        if self.name.trim().is_empty() { return Err("name must be non-empty"); }
        if self.description.trim().is_empty() { return Err("description must be non-empty"); }
        if self.metric_namespace.trim().is_empty() { return Err("metric_namespace must be non-empty"); }
        if self.metric_name.trim().is_empty() { return Err("metric_name must be non-empty"); }
        if self.aggregation.trim().is_empty() { return Err("aggregation must be non-empty"); }
        if self.operator.trim().is_empty() { return Err("operator must be non-empty"); }
        if self.window_size.trim().is_empty() { return Err("window_size must be non-empty"); }
        if self.evaluation_frequency.trim().is_empty() { return Err("evaluation_frequency must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct MetricAlertRefusal {
    pub alert_id: String,
    pub reason: String,
}

impl MetricAlertRefusal {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.alert_id.trim().is_empty() { return Err("alert_id must be non-empty"); }
        if self.reason.trim().is_empty() { return Err("reason must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct MetricAlertMaterialization {
    pub alerts: Vec<MaterializedMetricAlert>,
    pub refusals: Vec<MetricAlertRefusal>,
}

pub const METRIC_ALERT_DOCUMENT_SCHEMA: &str = "1.0.0";
pub const MODULE_AGGREGATIONS: &[&str] = &["Average", "Maximum", "Minimum", "Total", "Count"];
impl MetricAlertMaterialization {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn document(&self) -> std::collections::BTreeMap<String, String> {
        let body: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("schema_version"), String::from(METRIC_ALERT_DOCUMENT_SCHEMA)), (String::from("mode"), String::from("shadow")), (String::from("alerts"), String::new()), (String::from("refusals"), String::new())]);
        std::collections::BTreeMap::from([(String::from("digest"), String::new())])
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
#[allow(clippy::type_complexity)]
pub fn materialize_metric_alerts(mut entries: Vec<String>, mut templates: Option<std::collections::BTreeMap<String, String>>) -> MetricAlertMaterialization {
    let mut alerts: Vec<MaterializedMetricAlert> = Vec::<MaterializedMetricAlert>::new();
    let mut refusals: Vec<MetricAlertRefusal> = Vec::<MetricAlertRefusal>::new();
    MetricAlertMaterialization::default()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn refusal(mut entry: String, mut template: Option<String>) -> Option<String> {
    let Some(mut template) = template.clone() else { return Some(String::from("unknown_metric")); };
    None
}

pub const PUBLIC_EXPORTS: &[&str] = &["METRIC_ALERT_DOCUMENT_SCHEMA", "MaterializedMetricAlert", "MetricAlertMaterialization", "MetricAlertRefusal", "materialize_metric_alerts"];
