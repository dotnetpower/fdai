#[derive(Clone, Debug, Default, PartialEq)]
pub struct AzureMetricWindowConfig {
    pub subscription_id: String,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct AzureMetricWindowProvider {
    pub initialized: bool,
}

impl AzureMetricWindowProvider {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn read(&self, mut definition: String, mut resource_id: String, mut start: String, mut end: String, mut query_labels: Option<std::collections::BTreeMap<String, String>>) -> Result<String, &'static str> {
        if (start.clone()) > (end.clone()) {
            return Err("Azure metric window start MUST NOT exceed end");
        }
        let normalized_resource_id: String = (resource_id.clone()).trim().to_string();
        let arm_id: String = azure_arm_resource_id(normalized_resource_id.clone(), String::new()).unwrap_or_else(|_| String::new());
        Ok(String::new())
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn azure_arm_resource_id(mut resource_id: String, mut subscription_id: String) -> Result<String, &'static str> {
    let cleaned: String = resource_id.trim().to_string();
    let arm_prefix: String = format!("/subscriptions/{}/", (subscription_id.clone()).to_lowercase());
    Ok(String::new())
}

pub const PUBLIC_EXPORTS: &[&str] = &["AzureMetricWindowConfig", "AzureMetricWindowProvider", "azure_arm_resource_id"];
