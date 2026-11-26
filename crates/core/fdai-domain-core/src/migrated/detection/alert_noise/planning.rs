#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct AlertPlanHeld {
    pub message: String,
}

impl AlertPlanHeld {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for AlertPlanHeld {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for AlertPlanHeld {}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn plan_alert_change(mut evidence: String, mut treatment: String, mut policy: String, mut requester_ref: String, mut now: String, mut evaluation_receipt: Option<String>) -> Result<String, &'static str> {
    let _ = check_rule(String::new()).unwrap_or_else(|_| ());
    let mut action_type: String = String::from("ops.update-alert-routing");
    Ok(String::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn check_rule(mut rule: String) -> Result<(), &'static str> {
    Err("runtime_binding_required")
}

