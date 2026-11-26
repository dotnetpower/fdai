pub trait AzureMonitorMetricSampleClient {
    fn sample(&self, target_ref: String, metric_name: String, dimensions: std::collections::BTreeMap<String, String>, aggregation: String, observed_at: String) -> String;
}

pub trait OperatingScopeObservationReader {
    fn scope_state(&self, target_ref: String, signal_code: String, policy_revision: String) -> String;
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct AzureMonitorTestObservationProvider {
    pub initialized: bool,
}

impl AzureMonitorTestObservationProvider {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn observation(&self, mut coordinates: std::collections::BTreeMap<String, String>) -> Result<Option<std::collections::BTreeMap<String, String>>, &'static str> {
        let mut result: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("target_ref"), String::new()), (String::from("access_scope_digest"), String::new()), (String::from("signal_code"), String::new()), (String::from("observed_value"), String::new()), (String::from("observed_at"), String::new()), (String::from("service_impact"), String::new()), (String::from("protected_signal"), String::new()), (String::from("metric_name"), String::new()), (String::from("dimensions"), String::new()), (String::from("aggregation"), String::new()), (String::from("operating_scope_coverage"), String::new()), (String::from("dependency_health"), String::new()), (String::from("policy_revision"), String::new()), (String::from("source_anchor"), String::new())]);
        Ok(Some(result.clone()))
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct MetricProviderSampleClient {
    pub initialized: bool,
}

impl MetricProviderSampleClient {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn sample(&self, mut target_ref: String, mut metric_name: String, mut dimensions: std::collections::BTreeMap<String, String>, mut aggregation: String, mut observed_at: String) -> Option<std::collections::BTreeMap<String, String>> {
        let labels: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("resource_id"), target_ref.clone())]);
        let mut result: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("value"), String::new())]);
        Some(result.clone())
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct JsonOperatingScopeObservationReader {
    pub initialized: bool,
}

impl JsonOperatingScopeObservationReader {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn scope_state(&self, mut target_ref: String, mut signal_code: String, mut policy_revision: String) -> Option<std::collections::BTreeMap<String, String>> {
        if !self.initialized {
            return None;
        }
        None
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn required(mut row: std::collections::BTreeMap<String, String>, mut key: String) -> Result<String, &'static str> {
    let value: Option<String> = (row.clone()).get(key.as_str()).cloned();
    Ok((value.clone()).unwrap_or_default())
}

pub const PUBLIC_EXPORTS: &[&str] = &["AzureMonitorMetricSampleClient", "AzureMonitorTestObservationProvider", "JsonOperatingScopeObservationReader", "MetricProviderSampleClient", "OperatingScopeObservationReader"];
