pub const TERMINAL_STATES: &[&str] = &["succeeded", "rolled_back", "rollback_failed"];
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ActionRoutedExecutedActionObservationCollector {
    pub initialized: bool,
}

impl ActionRoutedExecutedActionObservationCollector {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn collect(&self, mut action: String, mut artifacts: String, mut execution_outcome: String, mut execution_completed_at: String, mut execution_receipt_ref: Option<String>, mut correlation_id: String) -> Option<String> {
        if !self.initialized {
            return None;
        }
        None
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct HeimdallExecutedActionObservationHandler {
    pub initialized: bool,
}

impl HeimdallExecutedActionObservationHandler {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn handle(&self, mut payload: std::collections::BTreeMap<String, String>) -> Result<bool, &'static str> {
        if ((payload.clone()).get("producer_principal").cloned()) != Some(String::from("Thor")) {
            return Err("executed ActionRun observation trigger MUST be produced by Thor");
        }
        let state: String = ((payload.clone()).get("state").cloned()).unwrap_or_else(|| String::from(""));
        let terminal_at_raw: Option<String> = (payload.clone()).get("terminal_at").cloned();
        if !(true) {
            return Err("executed ActionRun terminal timestamp MUST be text");
        }
        let correlation_id: String = ((payload.clone()).get("correlation_id").cloned()).unwrap_or_else(|| String::from(""));
        if ((correlation_id.clone()).is_empty()) || ((((correlation_id.clone()).len() as i64)) > (512_i64)) {
            return Err("executed ActionRun observation correlation MUST be bounded");
        }
        let shadow_mode: Option<String> = (payload.clone()).get("shadow_mode").cloned();
        if !(true) {
            return Err("executed ActionRun shadow mode MUST be boolean");
        }
        if let Some(mut shadow_mode) = shadow_mode.clone() {
            return Ok(false);
        }
        let receipt_ref: Option<String> = (payload.clone()).get("execution_audit_receipt").cloned();
        if (receipt_ref.is_some()) && (!(true)) {
            return Err("executed ActionRun receipt reference MUST be text or null");
        }
        Ok(true)
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["ActionRoutedExecutedActionObservationCollector", "HeimdallExecutedActionObservationHandler"];
