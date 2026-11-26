#[derive(Clone, Debug, Default, PartialEq)]
pub struct TransitionIntent {
    pub expected_revision: i64,
    pub target_state: String,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct AssignmentTransitionError {
    pub message: String,
}

impl AssignmentTransitionError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for AssignmentTransitionError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for AssignmentTransitionError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct StaleAssignmentRevisionError {
    pub message: String,
}

impl StaleAssignmentRevisionError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for StaleAssignmentRevisionError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for StaleAssignmentRevisionError {}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn validate_transition(mut current: String, mut candidate: String, mut transition: TransitionIntent) -> Result<(), &'static str> {
    if current.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn exact_inverse_progress(mut current: String, mut candidate: String) -> bool {
    if current.is_empty() {
        return false;
    }
    false
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn validate_recovery(mut candidate: String) -> Result<(), &'static str> {
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn validate_effect_order(mut current: String, mut candidate: String) -> Result<(), &'static str> {
    if current.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

pub const PUBLIC_EXPORTS: &[&str] = &["ALLOWED_TRANSITIONS", "AssignmentTransitionError", "StaleAssignmentRevisionError", "TransitionIntent", "validate_transition"];
