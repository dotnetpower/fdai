#[derive(Clone, Debug, Default, PartialEq)]
pub struct MetricWindowCoveragePolicy {
    pub minimum_samples: i64,
    pub maximum_samples: i64,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ProviderMetricWindowReader {
    pub initialized: bool,
}

impl ProviderMetricWindowReader {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn read(&self, mut definition: String, mut resource_id: String, mut start: String, mut end: String, mut query_labels: Option<std::collections::BTreeMap<String, String>>) -> Result<String, &'static str> {
        let mut points: Vec<String> = Vec::<String>::new();
        let mut truncated: bool = false;
        if truncated {
            let mut reason: String = String::from("sample_limit");
        } else {
            let mut reason: Option<String> = None;
        }
        Ok(String::new())
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["MetricWindowCoveragePolicy", "ProviderMetricWindowReader"];
