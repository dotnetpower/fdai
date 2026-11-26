pub const ACTION_TYPE: &str = "ops.scale-out";
pub const RESOURCE_TYPE: &str = "microsoft.compute/virtualmachinescalesets";
pub trait AzureObservationContextIssuer {
    fn issue(&self, evidence: String) -> String;
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct AzureScaleOutObservationCollector {
    pub initialized: bool,
}

impl AzureScaleOutObservationCollector {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn collect(&self, mut action: String, mut artifacts: String, mut execution_outcome: String, mut execution_completed_at: String, mut execution_receipt_ref: Option<String>, mut correlation_id: String) -> Result<Option<String>, &'static str> {
        if (execution_outcome.clone()) != (String::from("succeeded")) {
            return Ok(None);
        }
        let mut properties: std::collections::BTreeMap<String, f64> = std::collections::BTreeMap::<String, f64>::new();
        Ok(None)
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["AzureScaleOutObservationCollector", "AzureContainerAppScaleOutObservationCollector", "AzureObservationContextIssuer"];
