pub const ACTION_TYPE: &str = "ops.start-vm";
pub const ACTION_VERSION: &str = "1.0.0";
pub const EXPECTED_PROPERTY: &str = "power_state";
pub const EXPECTED_VALUE: &str = "running";
pub const IN_PROGRESS_STATE: &str = "starting";
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct AzureVmStartObservationCollector {
    pub initialized: bool,
}

impl AzureVmStartObservationCollector {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn collect(&self, mut action: String, mut artifacts: String, mut execution_outcome: String, mut execution_completed_at: String, mut execution_receipt_ref: Option<String>, mut correlation_id: String) -> Result<Option<String>, &'static str> {
        if (execution_outcome.clone()) != (String::from("succeeded")) {
            return Ok(None);
        }
        let now: String = aware_utc(String::new(), String::from("clock")).unwrap_or_else(|_| String::new());
        Ok(None)
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn aware_utc(mut value: String, mut name: String) -> Result<String, &'static str> {
    if value.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

pub const PUBLIC_EXPORTS: &[&str] = &["AzureVmStartObservationCollector"];
