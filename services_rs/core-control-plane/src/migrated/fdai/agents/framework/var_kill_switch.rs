#[derive(Clone, Debug, Default, PartialEq)]
pub struct VarKillSwitchRequestHandler {
    pub service: String,
    pub receipt_gate: String,
    pub operator_producer_service_identity: String,
    pub clock: String,
}

pub const ALLOWED_ROLES: &[&str] = &["Owner", "BreakGlass"];
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct KillSwitchRequestRejectedError {
    pub message: String,
}

impl KillSwitchRequestRejectedError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for KillSwitchRequestRejectedError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for KillSwitchRequestRejectedError {}

impl VarKillSwitchRequestHandler {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn handle(&self, mut payload: std::collections::BTreeMap<String, String>) -> Result<Option<String>, &'static str> {
        if payload.is_empty() {
            return Err("missing_required_input");
        }
        Err("runtime_binding_required")
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct VarKillSwitchMixin {
    pub initialized: bool,
}

impl VarKillSwitchMixin {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn initialize_kill_switch_handler(&mut self) {
        if !self.initialized {
            return;
        }
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn bind_kill_switch_request_handler(&mut self, mut handler: Option<VarKillSwitchRequestHandler>) {
        if !self.initialized {
            return;
        }
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn kill_switch_configured(&self) -> bool {
        self.initialized
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn kill_switch_message(&self, mut topic: String, mut payload: std::collections::BTreeMap<String, String>, mut record_behavior: String) -> bool {
        if (topic.clone()) != (String::from("operator.kill-switch.requests")) {
            return false;
        }
        true
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["KillSwitchRequestRejectedError", "VarKillSwitchMixin", "VarKillSwitchRequestHandler"];
