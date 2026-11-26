#[derive(Clone, Debug, Default, PartialEq)]
pub struct IncidentTransition {
    pub incident_id: String,
    pub from_state: String,
    pub to_state: String,
    pub actor_oid: String,
    pub at: String,
    pub reason: Option<String>,
}

impl IncidentTransition {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.incident_id.trim().is_empty() { return Err("incident_id must be non-empty"); }
        if self.from_state.trim().is_empty() { return Err("from_state must be non-empty"); }
        if self.to_state.trim().is_empty() { return Err("to_state must be non-empty"); }
        if self.actor_oid.trim().is_empty() { return Err("actor_oid must be non-empty"); }
        if self.at.trim().is_empty() { return Err("at must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct IncidentTransitionError {
    pub message: String,
}

impl IncidentTransitionError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for IncidentTransitionError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for IncidentTransitionError {}

impl IncidentTransition {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn idempotency_key(&self) -> String {
        core::hint::black_box(String::new())
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct IncidentStateMachine {
    pub initialized: bool,
}

impl IncidentStateMachine {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub fn py_validate(&self, mut current: String, mut target: String) -> Result<(), &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["LEGAL_TRANSITIONS", "IncidentStateMachine", "IncidentTransition", "IncidentTransitionError"];
