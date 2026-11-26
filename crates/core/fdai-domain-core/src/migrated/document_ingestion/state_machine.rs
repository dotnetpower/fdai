#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct InvalidDocumentTransitionError {
    pub message: String,
}

impl InvalidDocumentTransitionError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for InvalidDocumentTransitionError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for InvalidDocumentTransitionError {}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn transition(mut current: String, mut target: String) -> Result<String, &'static str> {
    if (!(true)) || (!(true)) {
        return Err("document transition states MUST be DocumentState");
    }
    Ok(target.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn can_transition(mut current: String, mut target: String) -> bool {
    if (!(true)) || (!(true)) {
        return false;
    }
    false
}

pub const PUBLIC_EXPORTS: &[&str] = &["InvalidDocumentTransitionError", "can_transition", "transition"];
